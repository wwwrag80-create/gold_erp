# -*- coding: utf-8 -*-
"""ملف الحساب (5.5 · دوال الخادم 3.2.0) — يرتّبه المدير العام فيصل جاهزاً.

لكل حسابٍ (مصنع · محل · عميل) ملفٌ على الخادم يحمل:

* **القائمة** (`nav`): ترتيب الشاشات وأسماؤها وتجميعها — وشاشاتٌ داخل
  شاشات — بصيغة ملف القائمة المحلي نفسه (`nav_layout.json`).
* **الهوية** (`identity`): اسم المنشأة وبياناتها وشعارها وختمها — بصيغة
  `services.branding` نفسها.

والقاعدة التي اختارها صاحب النظام:

* ملفُّ المدير يُطبَّق عند **أول دخولٍ بعد حفظه** (رقم إصداره أكبر مما
  طُبِّق على الجهاز).
* وما يعدّله المستخدم بعدها (ترتيبٌ أو اسمٌ أو هوية) يبقى له — حتى يحفظ
  المدير ملفاً جديداً فيُطبَّق هو.

رقم الإصدار المطبَّق يُحفظ في قاعدة المنشأة (`app_settings`) فينتقل مع
النسخة الاحتياطية، ولا يُطبَّق الملف نفسه مرتين.
"""
import json
from pathlib import Path

import config

# إصدار صيغة ملف القائمة — يطابق ما تقرؤه القائمة الجانبية
NAV_VERSION = 13
KEY_VER = "admin_profile_ver"
# حدٌّ آمن لحجم الملف قبل رفعه (الشعار والختم صورتان مصغّرتان)
MAX_BYTES = 3_500_000


def nav_path():
    """ملف القائمة بجوار قاعدة المنشأة — كما تحفظه القائمة الجانبية."""
    try:
        return Path(str(config.DB_PATH)).parent / "nav_layout.json"
    except Exception:
        return Path(str(config.BASE_DIR)) / "data" / "nav_layout.json"


# ══════════════════════════ القائمة ══════════════════════════
def default_nodes(screens=None):
    """القائمة الافتراضية بصيغة ملفها — مقيّدةً بشاشات الخطة إن أُعطيت."""
    from services import plan
    allow = set(screens) if screens else None

    def node(i, name):
        return {"idx": i, "key": name, "text": name, "expanded": False,
                "children": []}
    out, i = [], 1
    for name in plan.MAIN_SCREENS:
        if allow is None or name in allow:
            out.append(node(i, name))
        i += 1
    kids = []
    for name in plan.ADMIN_SCREENS:
        if allow is None or name in allow:
            kids.append(node(i, name))
        i += 1
    if kids:
        out.append({"idx": -1, "key": "::group::الإدارة والتقارير",
                    "text": "الإدارة والتقارير", "expanded": False,
                    "children": kids})
    return out


def clean_nodes(nodes):
    """يتحقّق من شجرة القائمة: كل شاشةٍ مرةً واحدة، ومجموعةٌ بلا شاشات
    تُحذف، والأسماء لا تكون فارغة."""
    from services import plan
    known = set(plan.ALL_SCREENS)
    seen = set()

    def walk(items):
        res = []
        for n in items or []:
            if not isinstance(n, dict):
                continue
            key = str(n.get("key") or "")
            text = str(n.get("text") or "").strip()
            kids = walk(n.get("children"))
            if key.startswith("::group::"):
                if not kids:
                    continue
                res.append({"idx": -1, "key": key,
                            "text": text or key[len("::group::"):],
                            "expanded": bool(n.get("expanded")),
                            "children": kids})
                continue
            if key not in known or key in seen:
                continue
            seen.add(key)
            idx = n.get("idx")
            res.append({"idx": idx if isinstance(idx, int) and idx > 0
                        else 1,
                        "key": key, "text": text or key,
                        "expanded": bool(n.get("expanded")),
                        "children": kids})
        return res
    return walk(nodes)


def complete_nodes(nodes):
    """يُكمل قائمة المدير بما لم يضعه فيها — فلا تُرمى شاشةٌ في غير مكانها.

    القائمة تُلحق الشاشة غير المذكورة بجوار جارتها الافتراضية، فلو نقص
    ملف المدير شاشاتٍ لدخلت مجموعةً رتّبها لغيرها. فتُلحق هنا: الشاشة
    الرئيسية في آخر القائمة، وشاشة الإدارة في مجموعة «الإدارة والتقارير»
    (أو مجموعةٍ بهذا الاسم تُنشأ في آخرها)."""
    from services import plan
    nodes = clean_nodes(nodes)
    have = set()

    def walk(items):
        for n in items:
            have.add(n["key"])
            walk(n.get("children") or [])
    walk(nodes)

    def node(name):
        return {"idx": 1, "key": name, "text": name, "expanded": False,
                "children": []}
    for name in plan.MAIN_SCREENS:
        if name not in have:
            nodes.append(node(name))
    miss = [node(n) for n in plan.ADMIN_SCREENS if n not in have]
    if miss:
        grp = next((n for n in nodes if n["key"].startswith("::group::")
                    and n["text"] == "الإدارة والتقارير"), None)
        if grp is None:
            grp = {"idx": -1, "key": "::group::الإدارة والتقارير",
                   "text": "الإدارة والتقارير", "expanded": False,
                   "children": []}
            nodes.append(grp)
        grp["children"].extend(miss)
    return nodes


def write_nav(nodes):
    p = nav_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": NAV_VERSION, "nodes": nodes},
                            ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ══════════════════════════ الملف كاملاً ══════════════════════════
def pack(nav_nodes=None, identity=None):
    """الملف كما يُرفع للخادم: نصّ JSON — ويُرفض إن جاوز الحد."""
    data = {"format": 1}
    if nav_nodes:
        data["nav"] = clean_nodes(nav_nodes)
    if identity:
        from services import branding
        errs = branding.validate(identity)
        if errs:
            raise ValueError("\n".join(errs))
        data["identity"] = branding._clean(identity)
    txt = json.dumps(data, ensure_ascii=False)
    if len(txt.encode("utf-8")) > MAX_BYTES:
        raise ValueError("ملف الحساب كبير جداً — صغّر الشعار أو الختم")
    return txt


def unpack(txt):
    if not txt:
        return {}
    try:
        d = json.loads(txt)
    except (TypeError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def applied_ver(conn):
    from models.fiscal import get_setting
    try:
        return int(get_setting(conn, KEY_VER, "0") or 0)
    except (TypeError, ValueError):
        return 0


def apply(conn, ver, txt, username=None):
    """يطبّق ملف المدير إن كان أحدث مما طُبِّق — ويعيد ما طُبِّق.

    القائمة تُكتب في ملفها المحلي (تقرؤه القائمة عند بنائها)، والهوية
    تُحفظ في قاعدة المنشأة وتُطبَّق فوراً. وخطأٌ في جزءٍ لا يمنع الآخر
    ولا يمنع الدخول أبداً."""
    from models.fiscal import set_setting
    ver = int(ver or 0)
    if ver <= applied_ver(conn):
        return []
    d = unpack(txt)
    done = []
    nodes = clean_nodes(d.get("nav") or [])
    if nodes:
        nodes = complete_nodes(nodes)
        try:
            write_nav(nodes)
            done.append("nav")
        except Exception:
            pass
    ident = d.get("identity")
    if isinstance(ident, dict) and ident.get("name"):
        try:
            from services import branding
            branding.save(conn, ident, username)
            done.append("identity")
        except Exception:
            pass
    set_setting(conn, KEY_VER, str(ver), username)
    return done
