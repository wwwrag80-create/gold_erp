#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ابحث عن كل قواعد بيانات النظام على هذا الجهاز.

    python tools/find_my_data.py

يمسح كل المسارات التي استعملها النظام في أي إصدار — مجلد المشروع،
ومجلد القرص الدائم، ومجلدات ويندوز، ومجلدات النسخ الاحتياطي — ويعرض
لكل ملف **ما فيه فعلاً**: عدد القيود والفواتير والجهات ومدى التواريخ.

**لماذا**: مسار قاعدة البيانات يعتمد على هوية المصنع النشطة، وهي تأتي
من حساب الدخول السحابي. فلو تغيّرت الهوية لأي سبب، فتح النظام مجلداً
جديداً فارغاً وبدت البيانات وكأنها ضاعت — وهي سليمة في مجلد الهوية
السابقة. هذه الأداة تُظهر أين هي بالضبط.

قراءة فقط — لا تعدّل ولا تحذف شيئاً.
"""
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

COUNTS = (
    ("قيود", "journal_entries", "is_deleted=0"),
    ("فواتير", "invoices", "is_deleted=0"),
    ("جهات", "entities", "is_deleted=0"),
    ("أطقم", "work_orders", "is_deleted=0"),
    ("حسابات", "accounts", ""),
)


def candidate_roots():
    """كل المجلدات التي قد يحفظ فيها النظام — في أي إصدار."""
    out, seen = [], set()

    def add(p, why):
        if not p:
            return
        try:
            p = Path(p).resolve()
        except Exception:
            return
        if str(p) in seen:
            return
        seen.add(str(p))
        out.append((p, why))

    add(ROOT, "مجلد المشروع")
    env = (os.environ.get("JADEITE_DATA_DIR") or "").strip()
    if env:
        add(env, "JADEITE_DATA_DIR")
    try:
        import config
        add(config.BASE_DIR, "المجلد الذي يستعمله النظام الآن")
    except Exception:
        pass
    if os.name == "nt":
        add("D:/TreeSoft_System/Data", "القرص D — مجلد النظام")
        add("D:/TreeSoft_Backups", "القرص D — النسخ الاحتياطي")
        add("C:/TreeSoft_Backups", "القرص C — النسخ الاحتياطي")
        appdata = os.environ.get("APPDATA")
        local = os.environ.get("LOCALAPPDATA")
        if appdata:
            add(Path(appdata) / "TreeSoft", "APPDATA/TreeSoft")
            add(Path(appdata) / "JadeiteERP", "APPDATA/JadeiteERP")
        if local:
            add(Path(local) / "JadeiteERP", "LOCALAPPDATA/JadeiteERP")
    else:
        add(Path.home() / ".treesoft", "مجلد النظام")
        add(Path.home() / ".treesoft_backups", "النسخ الاحتياطي")
        add(Path.home() / ".jadeite_erp", "مجلد بديل")
    return out


def find_dbs(root):
    """كل ملفات قواعد البيانات والنسخ تحت مجلد — بعمق محدود."""
    hits = []
    for pat in ("data/gold_erp.db", "data/gold_erp_legacy_backup.db",
                "gold_erp.db", "data/tenants/*/gold_erp.db",
                "*.bak", "backups/*.bak", "backups/*/*.bak",
                "*/*.bak", "backups/auto/*.db", "*.db"):
        try:
            hits += [p for p in root.glob(pat) if p.is_file()]
        except Exception:
            pass
    uniq, seen = [], set()
    for p in hits:
        s = str(p)
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq


def inspect(path):
    """ما بداخل الملف — أو سبب تعذّر القراءة."""
    info = {"size_mb": 0.0, "ok": False, "counts": {}, "span": "",
            "error": ""}
    try:
        info["size_mb"] = round(path.stat().st_size / 1048576, 2)
    except Exception:
        pass
    try:
        # للقراءة فقط، فلا يُنشأ ملف ولا يُعدَّل شيء
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3)
    except Exception as e:
        info["error"] = f"{type(e).__name__}"
        return info
    try:
        con.row_factory = sqlite3.Row
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "journal_entries" not in tables:
            info["error"] = "ليست قاعدة هذا النظام"
            return info
        info["ok"] = True
        for label, tbl, where in COUNTS:
            if tbl not in tables:
                continue
            try:
                q = f"SELECT COUNT(*) c FROM {tbl}"
                if where:
                    q += f" WHERE {where}"
                info["counts"][label] = con.execute(q).fetchone()["c"]
            except Exception:
                pass
        try:
            r = con.execute(
                "SELECT MIN(entry_date) a, MAX(entry_date) b"
                " FROM journal_entries WHERE is_deleted=0").fetchone()
            if r and r["a"]:
                info["span"] = f"{r['a']} ←→ {r['b']}"
        except Exception:
            pass
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {str(e)[:60]}"
    finally:
        try:
            con.close()
        except Exception:
            pass
    return info


def main():
    print("═" * 68)
    print("  البحث عن قواعد بيانات النظام على هذا الجهاز")
    print("═" * 68)

    try:
        import config
        active = str(config.DB_PATH)
    except Exception:
        active = ""

    found = []
    for root, why in candidate_roots():
        if not root.exists():
            continue
        dbs = find_dbs(root)
        if not dbs:
            continue
        print(f"\n▼ {root}")
        print(f"  ({why})")
        for p in sorted(dbs):
            i = inspect(p)
            mark = "◄ النشط الآن" if str(p) == active else ""
            rel = str(p)[len(str(root)):].lstrip("\\/") or p.name
            if not i["ok"]:
                print(f"    · {rel}  [{i['error'] or 'تعذّرت القراءة'}]")
                continue
            c = i["counts"]
            total = c.get("قيود", 0)
            summary = " · ".join(f"{k}: {v:,}" for k, v in c.items() if v)
            print(f"    {'★' if total else '·'} {rel}"
                  f"  ({i['size_mb']} م.ب)  {mark}")
            print(f"        {summary or 'فارغة'}")
            if i["span"]:
                print(f"        التواريخ: {i['span']}")
            found.append((total, p, i))

    print("\n" + "═" * 68)
    if not found:
        print("  لم يُعثر على أي قاعدة بيانات لهذا النظام.")
        return 1
    with_data = [f for f in found if f[0] > 0]
    if not with_data:
        print("  عُثر على قواعد لكنها كلها **فارغة** من القيود.")
        print("  راجع مجلدات النسخ الاحتياطي يدوياً، أو استرجع نسخة سحابية.")
        return 1
    with_data.sort(key=lambda f: -f[0])
    best_n, best_p, best_i = with_data[0]
    print(f"  أكبر قاعدة فيها بيانات:")
    print(f"     {best_p}")
    print(f"     {best_n:,} قيد" + (f" · {best_i['span']}" if best_i["span"]
                                   else ""))
    if active and str(best_p) != active:
        print("")
        print("  ⚠ النظام يفتح الآن ملفاً آخر:")
        print(f"     {active}")
        print("     بياناتك ليست ضائعة — النظام ينظر في المكان الخطأ.")
        print("     أرسل هذه المخرجات كاملةً لتحديد الخطوة الصحيحة.")
    print("═" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
