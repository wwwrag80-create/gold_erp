# -*- coding: utf-8 -*-
"""بيانات المنشأة والمشترين ومفاتيح الجهاز — كل ما يطلبه الربط.

**أين يُحفظ كل شيء**:
  · بيانات المنشأة (الاسم · الرقم الضريبي · السجل · العنوان الوطني)
    في `app_settings` — بيانات عامة تُطبع على كل فاتورة.
  · عنوان المشتري الوطني في `fatoora_buyers` — الفاتورة الضريبية
    (B2B) لا تُعتمد بلا عنوانٍ مفصّل للمشتري.
  · **المفتاح الخاص وشهادات الهيئة في ملفٍ على هذا الجهاز وحده**
    (مجلد المصنع/fatoora) — لا في قاعدة البيانات: القاعدة تُزامَن
    سحابياً وتُنسخ احتياطياً، والمفتاح سرٌّ لا يغادر الجهاز الذي
    سُجّل لدى الهيئة. ضياعه لا يُفقد فاتورة: تُطلب شهادةٌ جديدة
    برمز OTP جديد، والسلسلة تستمر من القاعدة.
"""
import json
import os
import re
import uuid
from pathlib import Path

import config

KEY = "fatoora.profile"
ENVS = (("simulation", "بيئة المحاكاة (للتجربة قبل الإطلاق)"),
        ("production", "البيئة الرسمية (الفواتير الحقيقية)"),
        ("sandbox", "بوابة المطوّرين (اختبار تقني فقط)"))
BASE_URLS = {
    "sandbox": "https://gw-fatoora.zatca.gov.sa/e-invoicing/developer-portal",
    "simulation": "https://gw-fatoora.zatca.gov.sa/e-invoicing/simulation",
    "production": "https://gw-fatoora.zatca.gov.sa/e-invoicing/core",
}
PAYMENT_MEANS = (("30", "آجل / تحويل (30)"), ("10", "نقداً (10)"),
                 ("42", "حساب بنكي (42)"), ("48", "بطاقة (48)"),
                 ("1", "غير محدد (1)"))
ID_SCHEMES = (("CRN", "السجل التجاري"), ("MOM", "ترخيص وزارة الموارد"),
              ("MLS", "ترخيص وزارة الشؤون البلدية"), ("700", "الرقم الموحّد 700"),
              ("SAG", "ترخيص الاستثمار"), ("OTH", "معرّف آخر"))

FIELDS = ("name", "vat", "crn", "crn_scheme", "street", "building", "plot",
          "district", "city", "postal", "additional_no", "branch", "industry",
          "env", "payment_means", "enabled", "egs_uuid", "activated_at")


def defaults():
    return {
        "name": getattr(config, "COMPANY_NAME", ""),
        "vat": getattr(config, "COMPANY_VAT_NUMBER", ""),
        "crn": getattr(config, "COMPANY_CR", ""),
        "crn_scheme": "CRN", "street": "", "building": "", "plot": "",
        "district": "", "city": "", "postal": "", "additional_no": "",
        "branch": "الفرع الرئيسي", "industry": "Gold Jewelry Manufacturing",
        "env": "simulation", "payment_means": "30", "enabled": False,
        "egs_uuid": "", "activated_at": "",
    }


def load(conn):
    from models.fiscal import get_setting
    data = defaults()
    try:
        raw = get_setting(conn, KEY, "")
        if raw:
            data.update({k: v for k, v in json.loads(raw).items()
                         if k in FIELDS})
    except Exception:
        pass
    return data


def save(conn, data, username=None):
    from models.fiscal import set_setting
    cur = load(conn)
    cur.update({k: v for k, v in (data or {}).items() if k in FIELDS})
    if not cur.get("egs_uuid"):
        cur["egs_uuid"] = str(uuid.uuid4())
    set_setting(conn, KEY, json.dumps(cur, ensure_ascii=False), username)
    return cur


# ══════════════════════════ التحقّق من الصيغ ══════════════════════════
def valid_vat(v):
    """الرقم الضريبي: 15 رقماً يبدأ بـ3 وينتهي بـ3 (BR-KSA-39/40)."""
    v = str(v or "").strip()
    return bool(re.fullmatch(r"3\d{13}3", v))


def valid_building(v):
    return bool(re.fullmatch(r"\d{4}", str(v or "").strip()))   # BR-KSA-37


def valid_postal(v):
    return bool(re.fullmatch(r"\d{5}", str(v or "").strip()))   # BR-KSA-66


def valid_crn(v, scheme="CRN"):
    v = str(v or "").strip()
    if scheme == "CRN":
        return bool(re.fullmatch(r"\d{10}", v))
    return bool(re.fullmatch(r"[A-Za-z0-9]{1,40}", v))


def seller_problems(p):
    """قائمة ما ينقص بيانات المنشأة — فارغةٌ إن اكتملت."""
    out = []
    if not str(p.get("name", "")).strip():
        out.append("الاسم القانوني للمنشأة")
    if not valid_vat(p.get("vat")):
        out.append("الرقم الضريبي (15 رقماً يبدأ بـ3 وينتهي بـ3)")
    if not valid_crn(p.get("crn"), p.get("crn_scheme") or "CRN"):
        out.append("السجل التجاري (10 أرقام)")
    if not str(p.get("street", "")).strip():
        out.append("اسم الشارع")
    if not valid_building(p.get("building")):
        out.append("رقم المبنى (4 أرقام)")
    if not str(p.get("district", "")).strip():
        out.append("الحي")
    if not str(p.get("city", "")).strip():
        out.append("المدينة")
    if not valid_postal(p.get("postal")):
        out.append("الرمز البريدي (5 أرقام)")
    return out


# ══════════════════════════ المشترون (B2B) ══════════════════════════
BUYER_FIELDS = ("street", "building", "district", "city", "postal",
                "additional_no", "crn")


def ensure_tables(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fatoora_buyers("
        " entity_id INTEGER PRIMARY KEY REFERENCES entities(id),"
        " street TEXT DEFAULT '', building TEXT DEFAULT '',"
        " district TEXT DEFAULT '', city TEXT DEFAULT '',"
        " postal TEXT DEFAULT '', additional_no TEXT DEFAULT '',"
        " crn TEXT DEFAULT '', updated_at TEXT)")


def buyer(conn, entity_id):
    ensure_tables(conn)
    e = conn.execute("SELECT id, name, vat_number, address FROM entities"
                     " WHERE id=?", (entity_id,)).fetchone()
    if not e:
        return None
    r = conn.execute("SELECT * FROM fatoora_buyers WHERE entity_id=?",
                     (entity_id,)).fetchone()
    out = {"entity_id": e["id"], "name": e["name"],
           "vat": str(e["vat_number"] or "").strip(),
           "address_text": e["address"] or ""}
    for f in BUYER_FIELDS:
        out[f] = (r[f] if r else "") or ""
    return out


def save_buyer(conn, entity_id, data):
    ensure_tables(conn)
    vals = [str((data or {}).get(f, "") or "").strip() for f in BUYER_FIELDS]
    conn.execute(
        "INSERT INTO fatoora_buyers(entity_id," + ",".join(BUYER_FIELDS)
        + ",updated_at) VALUES(?,?,?,?,?,?,?,?,datetime('now','localtime'))"
        " ON CONFLICT(entity_id) DO UPDATE SET "
        + ",".join(f"{f}=excluded.{f}" for f in BUYER_FIELDS)
        + ", updated_at=excluded.updated_at", [entity_id] + vals)


def buyer_is_b2b(b):
    """مشترٍ مسجّل بالضريبة = فاتورة ضريبية (اعتماد)، وإلا مبسطة (إبلاغ)."""
    return bool(b) and valid_vat(b.get("vat"))


def buyer_problems(b):
    """ما ينقص المشتري لفاتورةٍ ضريبية (BR-KSA-63/67)."""
    out = []
    if not str(b.get("street", "")).strip():
        out.append("الشارع")
    if not valid_building(b.get("building")):
        out.append("رقم المبنى (4 أرقام)")
    if not str(b.get("district", "")).strip():
        out.append("الحي")
    if not str(b.get("city", "")).strip():
        out.append("المدينة")
    if not valid_postal(b.get("postal")):
        out.append("الرمز البريدي (5 أرقام)")
    return out


# ══════════════════════════ مفاتيح الجهاز (EGS) ══════════════════════════
def keys_dir():
    try:
        d = Path(str(config.DB_PATH)).parent / "fatoora"
    except Exception:
        d = Path(config.BASE_DIR) / "data" / "fatoora"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _keys_path(env):
    return keys_dir() / f"egs_{env}.json"


def load_keys(env):
    p = _keys_path(env)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_keys(env, data):
    p = _keys_path(env)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, p)                          # كتابةٌ ذرّية
    try:
        os.chmod(p, 0o600)                      # للمالك وحده حيث يُدعم
    except Exception:
        pass
    return data


def active_credentials(env):
    """(الشهادة base64 · السرّ · المصدر) — الإنتاجية أولاً ثم الامتثال."""
    k = load_keys(env)
    prod = k.get("production") or {}
    if prod.get("token"):
        return prod["token"], prod.get("secret", ""), "production"
    comp = k.get("compliance") or {}
    if comp.get("token"):
        return comp["token"], comp.get("secret", ""), "compliance"
    return "", "", ""
