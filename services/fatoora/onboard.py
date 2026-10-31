# -*- coding: utf-8 -*-
"""خطوات التسجيل لدى الهيئة — بالترتيب الذي تشترطه بوابة «فاتورة».

  ① مفتاح الجهاز وطلب الشهادة (CSR) — محليّاً، بلا إنترنت
  ② رمز OTP من بوابة فاتورة ← شهادة الامتثال (Compliance CSID)
  ③ فحوص الامتثال: ستة مستندات تجريبية يتحقّق منها خادم الهيئة
     (فاتورة · إشعار دائن · إشعار مدين) × (ضريبية · مبسطة)
  ④ الشهادة الإنتاجية (Production CSID) — بها وحدها تُرسل الفواتير
  ⑤ تفعيل الإصدار والإرسال التلقائي مع كل فاتورة

كل خطوة تُحفظ نتيجتها في ملف مفاتيح الجهاز، فيُستأنف التسجيل من حيث
توقّف لو أُغلق البرنامج بين خطوتين.
"""
import uuid
from datetime import datetime

import config
from services.fatoora import api, ec, ubl
from services.fatoora import profile as pf

SAMPLES = (("standard", "invoice"), ("standard", "credit"),
           ("standard", "debit"), ("simplified", "invoice"),
           ("simplified", "credit"), ("simplified", "debit"))
SAMPLE_BUYER = {"name": "مشترٍ تجريبي لفحص الامتثال",
                "vat": "399999999800003", "street": "طريق الملك فهد",
                "building": "1234", "district": "العليا", "city": "الرياض",
                "postal": "12345", "crn": ""}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stage(env):
    """أين وصل تسجيل هذا الجهاز؟ (0..4) مع وصفٍ لكل خطوة."""
    k = pf.load_keys(env)
    checks = k.get("checks") or {}
    passed = sum(1 for v in checks.values() if v.get("ok"))
    return {
        "key": bool(k.get("private_key") and k.get("csr")),
        "compliance": bool((k.get("compliance") or {}).get("token")),
        "checks_passed": passed, "checks_total": len(SAMPLES),
        "checks": checks,
        "production": bool((k.get("production") or {}).get("token")),
        "keys": k,
    }


def generate(conn, env, username=None):
    """① مفتاحٌ جديد وطلب شهادة — يستبدل أي تسجيلٍ سابقٍ لهذه البيئة."""
    p = pf.load(conn)
    probs = pf.seller_problems(p)
    if probs:
        raise ValueError("أكمل بيانات المنشأة أولاً:\n• " + "\n• ".join(probs))
    key = ec.PrivateKey.generate()
    # 5.0.7: رقمٌ جديد لوحدة الفوترة مع كل تسجيل — جهازٌ جديد للمصنع (أو
    # إعادة تثبيت) وحدةٌ جديدة لدى الهيئة لا تحمل رقم وحدةٍ سابقة. والرقم
    # الضريبي يُحفظ مع الشهادة: لا تختم مصنعاً بشهادة غيره
    unit = str(uuid.uuid4())
    csr = _make_csr(p, key, env, unit)
    pf.save_keys(env, {"env": env, "private_key": key.to_pem(), "csr": csr,
                       "unit": unit, "vat": p["vat"],
                       "created_at": _now(), "created_by": username})
    return csr


def _make_csr(p, key, env, unit):
    addr = f"{p['building']} {p['street']}، {p['district']}، {p['city']} " \
           f"{p['postal']}"
    return ec.build_csr(
        key, common_name=f"GoldERP-{unit[:8]}-{p['vat']}",
        org=p["name"], org_unit=p.get("branch") or "الفرع الرئيسي",
        vat_number=p["vat"],
        egs_serial=f"1-GoldERP|2-{getattr(config, 'APP_VERSION', '1')}"
                   f"|3-{unit}",
        invoice_types="1100", address=addr,
        category=p.get("industry") or "Gold", env=env)


def request_compliance(env, otp):
    """② رمز OTP ← شهادة الامتثال."""
    k = pf.load_keys(env)
    if not k.get("csr"):
        raise ValueError("ولّد مفتاح الجهاز وطلب الشهادة أولاً (الخطوة ①)")
    if not str(otp or "").strip().isdigit():
        raise ValueError("رمز OTP أرقامٌ فقط — يُنسخ من بوابة فاتورة")
    r = api.compliance_csid(env, k["csr"], otp)
    k["compliance"] = {"token": r["binarySecurityToken"],
                       "secret": r.get("secret", ""),
                       "request_id": r.get("requestID"), "at": _now()}
    k.pop("checks", None)
    k.pop("production", None)
    pf.save_keys(env, k)
    return k["compliance"]


def _sample_doc(p, subtype, kind, icv, pih):
    doc = {
        "kind": kind, "subtype": subtype,
        "number": f"TST-{subtype[:3].upper()}-{kind[:3].upper()}-{icv}",
        "issue_date": datetime.now().strftime("%Y-%m-%d"),
        "issue_time": datetime.now().strftime("%H:%M:%S"),
        "icv": icv, "pih": pih,
        "seller": {f: str(p.get(f, "") or "") for f in
                   ("name", "vat", "crn", "crn_scheme", "street", "building",
                    "plot", "district", "city", "postal")},
        "buyer": dict(SAMPLE_BUYER) if subtype == "standard"
        else {"name": "عميل نقدي"},
        "lines": [{"name": "مصنعية طقم ذهب تجريبي — عيار 18: 10.000 جم",
                   "amount": 100.00}],
        "payment_means": p.get("payment_means") or "30",
    }
    if kind != "invoice":
        doc["billing_refs"] = ["TST-INV-1"]
        doc["reason"] = "إرجاع بضاعة" if kind == "credit" else \
            "تعديل سعر بالزيادة"
    return doc


def run_checks(conn, env, prof=None):
    """③ ستة مستندات تجريبية لخادم الامتثال — يعيد النتائج لكل نوع.

    `prof` (بيانات المنشأة مقروءةً سلفاً) مع `conn=None`: لا معاملة على
    القاعدة طوال الاتصال بالهيئة (5.0.6)."""
    k = pf.load_keys(env)
    comp = k.get("compliance") or {}
    if not comp.get("token"):
        raise ValueError("احصل على شهادة الامتثال أولاً (الخطوة ②)")
    p = prof or pf.load(conn)
    key = ec.PrivateKey.from_pem(k["private_key"])
    results = _compliance_round(env, key, comp["token"],
                                comp.get("secret", ""), p)
    k["checks"] = results
    pf.save_keys(env, k)
    return results


def _compliance_round(env, key, token, secret, p):
    """المستندات الستة لخادم الامتثال بشهادة الامتثال — نتيجة كلٍّ منها."""
    cert = api.token_certificate(token)
    pih, results = ubl.FIRST_PIH, {}
    for i, (sub, kind) in enumerate(SAMPLES, 1):
        signed = ubl.sign_document(_sample_doc(p, sub, kind, i, pih), key,
                                   cert)
        pih = signed["hash"]
        name = f"{sub}:{kind}"
        try:
            st, payload = api.compliance_check(env, token, secret, signed)
            errs, warns = api.messages(payload)
            rs = str(payload.get("clearanceStatus")
                     or payload.get("reportingStatus") or "").upper()
            ok = st in (200, 202) and rs in ("CLEARED", "REPORTED")
            results[name] = {"ok": ok, "status": st, "result": rs,
                             "errors": errs, "warnings": warns, "at": _now()}
        except api.ApiError as e:
            results[name] = {"ok": False, "status": e.status, "result": "",
                             "errors": [str(e)], "warnings": [],
                             "at": _now()}
    return results


def request_production(env):
    """④ الشهادة الإنتاجية — لا تُطلب إلا بعد نجاح الفحوص الستة."""
    k = pf.load_keys(env)
    comp = k.get("compliance") or {}
    checks = k.get("checks") or {}
    if not comp.get("token"):
        raise ValueError("احصل على شهادة الامتثال أولاً (الخطوة ②)")
    failed = [n for n, v in checks.items() if not v.get("ok")]
    if len(checks) < len(SAMPLES) or failed:
        raise ValueError("يجب أن تنجح فحوص الامتثال الستة أولاً (الخطوة ③)")
    r = api.production_csid(env, comp["token"], comp.get("secret", ""),
                            comp.get("request_id"))
    cert_txt = api.token_certificate(r["binarySecurityToken"])
    expires = ""
    try:
        expires = ec.Certificate.from_b64(cert_txt).not_after
    except Exception:
        pass
    k["production"] = {"token": r["binarySecurityToken"],
                       "secret": r.get("secret", ""),
                       "request_id": r.get("requestID"), "at": _now(),
                       "expires": expires}
    pf.save_keys(env, k)
    return k["production"]


# ══════════════════════ 🧪 تجربة الإرسال بلا فواتير حقيقية (5.0.6) ══════════
# بعد الشهادة الإنتاجية في بيئة المحاكاة: يُرسل مستنداتٍ تجريبية بالطريق
# نفسه الذي ستُرسل به الفواتير (الإبلاغ للمبسطة · الاعتماد للضريبية)
# وبالشهادة الإنتاجية نفسها — فيُعرف أن الربط يعمل فعلاً من أوله إلى
# آخره. **ولا يُكتب شيءٌ في دفاتر المصنع**: لا مستند في سجل الفواتير
# الإلكترونية، ولا عدّاد يتقدّم، ولا فاتورةٌ تُقفل. وتُرفض في البيئة
# الرسمية: كل ما يُرسل هناك فاتورةٌ حقيقية لدى الهيئة.
TRIAL_ENVS = ("simulation", "sandbox")


def _trial_docs(conn, p):
    stamp = datetime.now().strftime("%m%d%H%M%S")
    docs = []
    for sub, title in (("simplified", "فاتورة مبسطة (إبلاغ)"),
                       ("standard", "فاتورة ضريبية (اعتماد)")):
        d = _sample_doc(p, sub, "invoice", 0, "")
        d["number"] = f"TRIAL-{sub[:3].upper()}-{stamp}"
        docs.append((title, d))
    # نسخةٌ من آخر فاتورة بيعٍ ضريبية حقيقية — تكشف ما ينقص بياناتك أنت
    # (عنوان العميل، أسطر الطقم…) قبل الإطلاق. برقمٍ تجريبي، ولا تُمسّ.
    try:
        from services.fatoora import ledger
        r = conn.execute(
            "SELECT i.id FROM invoices i JOIN entities e ON"
            " e.id=i.customer_id WHERE i.is_deleted=0 AND i.vat_applied=1"
            " AND i.kind='sale' AND e.entity_type<>'internal'"
            " ORDER BY i.id DESC LIMIT 1").fetchone()
        if r:
            d = ledger.build_doc(conn, r["id"], p)
            title = f"نسخة من فاتورتك {d['number']}"
            d["number"] = f"TRIAL-COPY-{stamp}"
            d["issue_date"] = datetime.now().strftime("%Y-%m-%d")
            d["issue_time"] = datetime.now().strftime("%H:%M:%S")
            d["supply_date"] = d["issue_date"]
            docs.append((title, d))
    except Exception:
        pass
    return docs


def trial_send(env):
    """يرسل المستندات التجريبية للمحاكاة ويعيد نتيجة كلٍّ منها.

    لا يكتب في قاعدة المصنع شيئاً — النتيجة تُحفظ في ملف مفاتيح الجهاز
    لهذه البيئة ليقرأها فحص الجاهزية. والقاعدة تُقرأ في معاملةٍ قصيرة
    تُغلق قبل أي اتصال: الشبكة لا تحبس قفلها."""
    from database.database import db
    from services.fatoora import ledger
    if env not in TRIAL_ENVS:
        raise ValueError("التجربة في بيئة المحاكاة وحدها — كل ما يُرسل في "
                         "البيئة الرسمية فاتورةٌ حقيقية لدى الهيئة.")
    k = pf.load_keys(env)
    prod = k.get("production") or {}
    if not prod.get("token"):
        raise ValueError("التجربة تحتاج الشهادة الإنتاجية لبيئة المحاكاة "
                         "(الخطوة ④) — بها تُرسل الفواتير.")
    with db(readonly=True) as conn:
        p = pf.load(conn)
        docs = _trial_docs(conn, p)
    key = ec.PrivateKey.from_pem(k["private_key"])
    chain = k.get("trial_chain") or {}
    out, icv, pih = _send_samples(
        env, key, prod["token"], prod.get("secret", ""), docs,
        int(chain.get("icv") or 0), chain.get("pih") or ubl.FIRST_PIH)
    ok = bool(out) and all(r["status"] in ledger.ACCEPTED for r in out)
    k["trial_chain"] = {"icv": icv, "pih": pih}
    k["trial"] = {"at": _now(), "ok": ok, "results": out}
    pf.save_keys(env, k)
    return k["trial"]


def _send_samples(env, key, token, secret, docs, icv=0, pih=None):
    """يرسل مستنداتٍ بالطريق الحقيقي (إبلاغ/اعتماد) بالشهادة الإنتاجية."""
    from services.fatoora import ledger, rules
    cert = api.token_certificate(token)
    pih = pih or ubl.FIRST_PIH
    out = []
    for title, doc in docs:
        icv += 1
        doc = dict(doc, icv=icv, pih=pih)
        res = {"title": title, "number": doc["number"],
               "subtype": doc["subtype"], "status": "", "label": "",
               "errors": [], "warnings": [], "local": False}
        errs, _w = rules.check_document(doc)
        if errs:
            res.update(status="local", local=True, errors=errs[:8],
                       label="لم تُرسل — بياناتٌ ناقصة")
            icv -= 1
            out.append(res)
            continue
        signed = ubl.sign_document(doc, key, cert)
        pih = signed["hash"]
        try:
            st, payload = api.submit(env, token, secret, signed["hash"],
                                     signed["uuid"], signed["xml"],
                                     doc["subtype"] == "standard")
            status, error = ledger.interpret(st, payload)
        except api.ApiError as e:
            status, payload, error = "error", {}, str(e)
        e2, w2 = api.messages(payload)
        res.update(status=status,
                   label=ledger.STATUS_LABELS.get(status, status),
                   errors=e2 or ([error] if error and status != "warning"
                                 else []),
                   warnings=w2)
        out.append(res)
    return out, icv, pih


# ══════════════ ⚡ الاختبار السريع — بلا بيانات المنشأة (5.0.7) ══════════════
# يجيب عن سؤالٍ واحد قبل أي إدخال: **هل هذا الجهاز وهذا النظام يتكلّمان
# مع خادم الهيئة كما يجب؟** يجري الدورة كلّها على «بوابة المطوّرين» لدى
# الهيئة (بيئة اختبارٍ تقني تقبل بياناتٍ تجريبية ورمز OTP ثابتاً):
#   مفتاح وطلب شهادة ← شهادة امتثال ← الفحوص الستة ← شهادة إنتاجية ←
#   إبلاغ فاتورة مبسطة واعتماد فاتورة ضريبية
# ببيانات منشأةٍ تجريبية في الذاكرة وحدها: لا يُكتب في قاعدة المصنع شيء،
# ولا تُمسّ بيانات المنشأة ولا شهادات المحاكاة أو الرسمية. والنتيجة وحدها
# تُحفظ لفحص الجاهزية.
#
# ما يثبته: الإنترنت إلى الهيئة · ساعة الجهاز · طلب الشهادة والختم
# والبصمة والمستند بصيغة يقبلها خادم الهيئة. وما لا يثبته: بيانات منشأتك
# أنت — تلك تثبتها «تجربة الإرسال» في المحاكاة.
DEV_ENV = "sandbox"
DEV_OTP = "123345"           # رمز بوابة المطوّرين الثابت (وثائق الهيئة)
DEV_SELLER = {
    "name": "شركة اختبار تقني لنظام الذهب", "vat": "399999999900003",
    "crn": "1010010000", "crn_scheme": "CRN", "street": "طريق الملك فهد",
    "building": "1234", "plot": "", "district": "العليا",
    "city": "الرياض", "postal": "12345", "branch": "اختبار تقني",
    "industry": "Gold Jewelry Manufacturing", "payment_means": "10",
}
QUICK_STEPS = ("طلب الشهادة (CSR) والمفتاح", "شهادة الامتثال من الهيئة",
               "فحوص الامتثال الستة", "الشهادة الإنتاجية",
               "إبلاغ فاتورة مبسطة واعتماد فاتورة ضريبية")


def _quick_path():
    return pf.keys_dir() / "quick_test.json"


def last_quick_test():
    import json
    try:
        return json.loads(_quick_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def quick_test(otp=None, on_step=None):
    """الدورة كاملةً مع بوابة المطوّرين ببياناتٍ تجريبية — يعيد كل خطوة.

    `on_step(i, title)` تُنادى قبل كل خطوة (لتقول الواجهة أين وصل)."""
    import json
    import os
    steps = []

    def _step(i):
        if on_step:
            try:
                on_step(i, QUICK_STEPS[i])
            except Exception:
                pass

    def _done(ok, detail=""):
        steps.append({"title": QUICK_STEPS[len(steps)], "ok": bool(ok),
                      "detail": str(detail)[:900]})
        return ok

    p = dict(DEV_SELLER)
    try:
        _step(0)
        key = ec.PrivateKey.generate()
        csr = _make_csr(p, key, DEV_ENV, str(uuid.uuid4()))
        _done(True, "وُلّدا على هذا الجهاز")
        _step(1)
        comp = api.compliance_csid(DEV_ENV, csr, otp or DEV_OTP)
        _done(True, "أصدرتها الهيئة")
        _step(2)
        res = _compliance_round(DEV_ENV, key, comp["binarySecurityToken"],
                                comp.get("secret", ""), p)
        bad = {n: v for n, v in res.items() if not v["ok"]}
        if not _done(not bad, "نجحت الستة" if not bad else "؛ ".join(
                f"{n}: " + "، ".join(v["errors"][:2]) for n, v in
                bad.items())):
            raise _Stop()
        _step(3)
        prod = api.production_csid(DEV_ENV, comp["binarySecurityToken"],
                                   comp.get("secret", ""),
                                   comp.get("requestID"))
        _done(True, "أصدرتها الهيئة")
        _step(4)
        docs = []
        stamp = datetime.now().strftime("%m%d%H%M%S")
        for sub, title in (("simplified", "مبسطة"), ("standard", "ضريبية")):
            d = _sample_doc(p, sub, "invoice", 0, "")
            d["number"] = f"QT-{sub[:3].upper()}-{stamp}"
            docs.append((title, d))
        out, _i, _h = _send_samples(DEV_ENV, key,
                                    prod["binarySecurityToken"],
                                    prod.get("secret", ""), docs)
        from services.fatoora import ledger
        ok = all(r["status"] in ledger.ACCEPTED for r in out)
        _done(ok, "  ·  ".join(
            f"{r['title']}: {r['label']}" + (
                " — " + "، ".join(r["errors"][:2]) if r["errors"] else "")
            for r in out))
    except _Stop:
        pass
    except api.ApiError as e:
        _done(False, str(e))
    except Exception as e:                       # noqa: BLE001
        _done(False, f"{type(e).__name__}: {e}")
    skew = api.LAST.get("server_skew")
    result = {"at": _now(), "ok": len(steps) == len(QUICK_STEPS)
              and all(s["ok"] for s in steps), "steps": steps,
              "reachable": api.LAST.get("reachable"),
              "clock_skew": skew}
    try:
        path = _quick_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass
    return result


class _Stop(Exception):
    pass


def set_enabled(conn, on, username=None):
    """⑤ تفعيل الإصدار — لا يُفعَّل بلا شهادة إنتاجية."""
    p = pf.load(conn)
    env = p.get("env") or "simulation"
    if on and not stage(env)["production"]:
        raise ValueError("لا يُفعَّل الربط قبل الحصول على الشهادة الإنتاجية "
                         "(الخطوة ④)")
    data = {"enabled": bool(on)}
    if on:
        # من هذه اللحظة كل فاتورةٍ ضريبية يجب أن يكون لها مستند — وفحص
        # الجاهزية يعدّ ما صدر بعدها بلا مستند
        data["activated_at"] = _now()
    return pf.save(conn, data, username)
