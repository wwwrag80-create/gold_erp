# -*- coding: utf-8 -*-
"""واجهات بوابة «فاتورة» — التسجيل والامتثال والإبلاغ والاعتماد.

  POST /compliance                 رمز OTP + طلب الشهادة ← شهادة امتثال
  POST /compliance/invoices        مستندات تجريبية ← نتيجة فحص الامتثال
  POST /production/csids           معرّف طلب الامتثال ← الشهادة الإنتاجية
  POST /invoices/reporting/single  فاتورة مبسطة ← «أُبلغت» (خلال 24 ساعة)
  POST /invoices/clearance/single  فاتورة ضريبية ← «اعتُمدت» + نسخة مختومة

بمكتبة بايثون القياسية وحدها (urllib) — لا اعتماد على حزمٍ إضافية.
ويُسجَّل فرق ساعة الجهاز عن ساعة البوابة مع كل ردّ: الهيئة تشترط أن
تكون ساعة جهاز الفوترة مضبوطة، وهذا يكشف انحرافها بلا أداةٍ أخرى.
"""
import base64
import json
import time
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime

from services.fatoora import profile as pf

LAST = {"server_skew": None, "checked_at": None, "reachable": None}


class ApiError(Exception):
    def __init__(self, msg, status=0, body=None):
        super().__init__(msg)
        self.status = status
        self.body = body or {}


def _auth(token, secret):
    raw = f"{token}:{secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def call(env, path, body=None, *, otp=None, token=None, secret=None,
         clearance=None, method="POST", timeout=40):
    """ينادي البوابة ويعيد (رمز الحالة, الجسم dict)."""
    # تجاوزٌ للاختبار الآلي وحده (خادم محاكٍ محلي) — لا يُضبط في التشغيل
    import os
    base = os.environ.get("GOLD_ERP_FATOORA_URL") or pf.BASE_URLS[env]
    url = base.rstrip("/") + path
    headers = {"Accept": "application/json", "Accept-Language": "ar",
               "Accept-Version": "V2", "Content-Type": "application/json"}
    if otp:
        headers["OTP"] = str(otp).strip()
    if token:
        headers["Authorization"] = _auth(token, secret or "")
    if clearance is not None:
        headers["Clearance-Status"] = "1" if clearance else "0"
    data = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers)
    status, raw, hdrs = 0, b"", {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw, hdrs = r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        status, raw, hdrs = e.code, e.read() or b"", dict(e.headers or {})
    except Exception as e:                         # شبكة · شهادة · مهلة
        LAST["reachable"] = False
        raise ApiError(f"تعذّر الاتصال ببوابة فاتورة: {e}", 0)
    LAST["reachable"] = True
    _note_clock(hdrs)
    try:
        payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except Exception:
        payload = {"raw": raw.decode("utf-8", "replace")[:2000]}
    return status, payload


def _note_clock(hdrs):
    try:
        d = hdrs.get("Date") or hdrs.get("date")
        if d:
            server = parsedate_to_datetime(d).timestamp()
            LAST["server_skew"] = round(time.time() - server, 1)
            LAST["checked_at"] = time.time()
    except Exception:
        pass


def messages(payload):
    """رسائل الأخطاء والتنبيهات من ردّ الهيئة — نصوصٌ مقروءة."""
    vr = (payload or {}).get("validationResults") or {}
    errs = [f"{m.get('code', '')}: {m.get('message', '')}"
            for m in vr.get("errorMessages") or []]
    warns = [f"{m.get('code', '')}: {m.get('message', '')}"
             for m in vr.get("warningMessages") or []]
    for m in (payload or {}).get("errors") or []:
        if isinstance(m, dict):
            errs.append(f"{m.get('code', '')}: {m.get('message', '')}")
        else:
            errs.append(str(m))
    if not errs and (payload or {}).get("message") and \
            not (payload or {}).get("validationResults"):
        errs.append(str(payload.get("message")))
    return errs, warns


# ══════════════════════════ التسجيل ══════════════════════════
def compliance_csid(env, csr_pem, otp):
    body = {"csr": base64.b64encode(csr_pem.encode("ascii")).decode("ascii")}
    st, p = call(env, "/compliance", body, otp=otp)
    if st != 200 or not p.get("binarySecurityToken"):
        errs, _w = messages(p)
        raise ApiError("رفضت الهيئة طلب شهادة الامتثال: "
                       + ("؛ ".join(errs) or f"رمز {st}"), st, p)
    return p


def compliance_check(env, token, secret, signed):
    body = {"invoiceHash": signed["hash"], "uuid": signed["uuid"],
            "invoice": base64.b64encode(signed["xml"].encode("utf-8"))
            .decode("ascii")}
    return call(env, "/compliance/invoices", body, token=token,
                secret=secret)


def production_csid(env, token, secret, request_id):
    st, p = call(env, "/production/csids",
                 {"compliance_request_id": str(request_id)},
                 token=token, secret=secret)
    if st != 200 or not p.get("binarySecurityToken"):
        errs, _w = messages(p)
        raise ApiError("تعذّر إصدار الشهادة الإنتاجية: "
                       + ("؛ ".join(errs) or f"رمز {st}"), st, p)
    return p


# ══════════════════════════ الإرسال ══════════════════════════
def submit(env, token, secret, doc_hash, doc_uuid, xml, standard):
    body = {"invoiceHash": doc_hash, "uuid": doc_uuid,
            "invoice": base64.b64encode(xml.encode("utf-8")).decode("ascii")}
    path = ("/invoices/clearance/single" if standard
            else "/invoices/reporting/single")
    return call(env, path, body, token=token, secret=secret,
                clearance=bool(standard))


def token_certificate(token):
    """binarySecurityToken ← نص الشهادة (DER base64) الذي يُختم به."""
    return base64.b64decode(token).decode("ascii").strip()


def ping(env):
    """اختبار الوصول للبوابة: أي ردٍّ منها (ولو رفض) يعني أنها مُتاحة."""
    try:
        st, _p = call(env, "/compliance", {"csr": ""}, timeout=15)
        return True, st
    except ApiError as e:
        return False, str(e)
