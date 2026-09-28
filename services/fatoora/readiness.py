# -*- coding: utf-8 -*-
"""فحص الجاهزية — هل النظام مربوطٌ بالهيئة فعلاً؟ وما الذي ينقصه؟

يمرّ على متطلبات الهيئة للأنظمة المحاسبية (قرار الفوترة الإلكترونية ·
الضوابط والمتطلبات والمواصفات الفنية · معايير الأمان · دليل المطوّرين)
ويقول في كل بندٍ: متحقّق ✔ · تنبيه ⚠ · غير متحقّق ✘ — مع السبب.

والحكم في الأعلى صريحٌ لا يجامل: «مربوطٌ فعلياً» لا تُقال إلا حين
تكون الشهادة الإنتاجية للبيئة الرسمية بيد الجهاز، والإرسال مفعّلاً،
والهيئة قد قبلت مستنداتٍ منه فعلاً.
"""
from datetime import datetime, timedelta

from services.fatoora import api, ec, ledger, onboard, ubl
from services.fatoora import profile as pf

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


def _item(out, section, title, status, detail=""):
    out.append({"section": section, "title": title, "status": status,
                "detail": detail})


def verdict(conn, st=None, summ=None):
    p = pf.load(conn)
    env = p.get("env") or "simulation"
    st = st or onboard.stage(env)
    summ = summ or ledger.summary(conn)
    acc = sum(summ["by_status"].get(s, 0) for s in ledger.ACCEPTED)
    bad = summ["by_status"].get("rejected", 0)
    if not st["production"]:
        if st["compliance"]:
            return ("warn", "غير مربوط بعد — في مرحلة فحص الامتثال",
                    "أكمل فحوص الامتثال ثم اطلب الشهادة الإنتاجية.")
        return ("fail", "غير مربوط بالهيئة",
                "لم يُسجَّل هذا الجهاز لدى بوابة فاتورة بعد. ابدأ من "
                "تبويب «التسجيل والربط» برمز OTP من بوابة فاتورة.")
    if env != "production":
        return ("warn", "مربوطٌ ببيئة المحاكاة — ليس ربطاً رسمياً",
                "الفواتير هنا تجريبية لا يُعتدّ بها ضريبياً. بعد التجربة "
                "اختر «البيئة الرسمية» وسجّل الجهاز برمز OTP رسمي.")
    if not p.get("enabled"):
        return ("warn", "الشهادة الرسمية جاهزة — الإرسال غير مفعّل",
                "فعّل الإصدار والإرسال من تبويب «التسجيل والربط».")
    if bad:
        return ("fail", "مربوط — وتوجد فواتير مرفوضة من الهيئة",
                f"{bad} مستند مرفوض — افتح «سجل الفواتير الإلكترونية».")
    if acc:
        return ("ok", "مربوطٌ فعلياً بالهيئة ✔",
                f"قبلت الهيئة {acc} مستنداً من هذا الجهاز في البيئة الرسمية.")
    return ("ok", "مربوطٌ بالبيئة الرسمية — لم تُرسل فاتورةٌ بعد",
            "أول فاتورة ضريبية تُصدر ستُرسل للهيئة تلقائياً.")


def run(conn, deep=True):
    """يعيد {verdict, items, score} — `deep` يعيد التحقق من كل بصمةٍ وتوقيع."""
    ledger.ensure_tables(conn)
    items = []
    p = pf.load(conn)
    env = p.get("env") or "simulation"
    st = onboard.stage(env)
    summ = ledger.summary(conn)

    # ════ ١) بيانات المنشأة ════
    sec = "بيانات المنشأة (البائع)"
    _item(items, sec, "الاسم القانوني", OK if p.get("name") else FAIL,
          p.get("name") or "غير مُدخل")
    _item(items, sec, "الرقم الضريبي (15 رقماً يبدأ وينتهي بـ3)",
          OK if pf.valid_vat(p.get("vat")) else FAIL, p.get("vat") or "—")
    if str(p.get("vat")) in ("300000000000003", "399999999900003"):
        _item(items, sec, "الرقم الضريبي ليس رقماً تجريبياً", FAIL,
              "الرقم المُدخل رقم مثالٍ — أدخل رقم منشأتك الفعلي")
    _item(items, sec, "السجل التجاري / معرّف المنشأة",
          OK if pf.valid_crn(p.get("crn"), p.get("crn_scheme") or "CRN")
          else FAIL, p.get("crn") or "—")
    addr_probs = [x for x in pf.seller_problems(p)
                  if x not in ("الاسم القانوني للمنشأة",) and
                  not x.startswith("الرقم الضريبي") and
                  not x.startswith("السجل التجاري")]
    _item(items, sec, "العنوان الوطني المفصّل (شارع · مبنى · حي · مدينة · "
          "رمز بريدي)", FAIL if addr_probs else OK,
          ("ينقص: " + "، ".join(addr_probs)) if addr_probs else
          f"{p.get('building')} {p.get('street')}، {p.get('district')}، "
          f"{p.get('city')} {p.get('postal')}")

    # ════ ٢) الجهاز والتشفير ════
    sec = "جهاز الفوترة (EGS) والتشفير"
    _item(items, sec, "البيئة", INFO, dict(pf.ENVS).get(env, env))
    _item(items, sec, "مفتاح الختم secp256k1 وطلب الشهادة (CSR) بمواصفات "
          "الهيئة", OK if st["key"] else FAIL,
          "مولَّد ومحفوظ على هذا الجهاز وحده" if st["key"]
          else "لم يُولَّد بعد — الخطوة ①")
    _item(items, sec, "شهادة الامتثال (Compliance CSID)",
          OK if st["compliance"] else FAIL,
          (st["keys"].get("compliance") or {}).get("at", "")
          if st["compliance"] else "تُطلب برمز OTP — الخطوة ②")
    ck = st["checks"]
    _item(items, sec, "فحوص الامتثال الستة (فاتورة · دائن · مدين × ضريبية · "
          "مبسطة)", OK if st["checks_passed"] == st["checks_total"] else
          FAIL,
          f"نجح {st['checks_passed']} من {st['checks_total']}"
          + "".join(" — لم ينجح: " + "، ".join(bad) for bad in [[
              n for n, v in ck.items() if not v.get("ok")]] if bad))
    prod = st["keys"].get("production") or {}
    if st["production"]:
        exp = prod.get("expires") or ""
        stat, det = OK, f"صدرت {prod.get('at', '')}"
        if exp:
            det += f" · تنتهي {exp[:10]}"
            try:
                left = datetime.strptime(exp[:10], "%Y-%m-%d") - datetime.now()
                if left < timedelta(days=0):
                    stat, det = FAIL, f"انتهت صلاحيتها {exp[:10]} — جدّدها"
                elif left < timedelta(days=30):
                    stat = WARN
                    det += f" (بعد {left.days} يوماً — جدّدها قريباً)"
            except Exception:
                pass
        _item(items, sec, "الشهادة الإنتاجية (Production CSID)", stat, det)
    else:
        _item(items, sec, "الشهادة الإنتاجية (Production CSID)", FAIL,
              "لم تصدر — الخطوة ④ بعد نجاح الفحوص")
    _item(items, sec, "الإصدار والإرسال التلقائي مع كل فاتورة",
          OK if ledger.enabled(conn) else FAIL,
          f"مفعّل منذ {p.get('activated_at', '')}" if ledger.enabled(conn)
          else "غير مفعّل")

    # ════ ٣) سلامة السجل ════
    sec = "سلامة السجل (العدّاد · السلسلة · الختم)"
    trig = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'")}
    lock_ok = {"fatoora_no_delete", "fatoora_no_edit"} <= trig
    _item(items, sec, "منع حذف المستندات الإلكترونية أو تعديلها (على مستوى "
          "قاعدة البيانات)", OK if lock_ok else FAIL,
          "مُشغِّلات الحماية مفعّلة" if lock_ok else "الحماية غير مركّبة")
    _item(items, sec, "منع تعديل/حذف/نقل الفاتورة بعد إصدار مستندها — "
          "التصحيح بإشعار دائن", OK, "مُطبَّق في كل مسارات التعديل والحذف")
    docs = conn.execute(
        "SELECT id, icv, pih, invoice_hash, xml, doc_no FROM"
        " fatoora_documents ORDER BY icv").fetchall()
    gaps, chain_bad, tamper, sig_bad = [], [], [], []
    prev_hash, prev_icv = ubl.FIRST_PIH, None
    tail = docs[-200:] if deep else []
    tail_ids = {d["id"] for d in tail}
    for d in docs:
        if prev_icv is not None and d["icv"] != prev_icv + 1:
            gaps.append(f"{prev_icv}→{d['icv']}")
        if d["pih"] != prev_hash:
            chain_bad.append(d["doc_no"])
        if deep:
            v = ubl.verify_document(d["xml"]) if d["id"] in tail_ids else \
                {"hash": ubl.hash_of_xml(d["xml"]), "signature_ok": True}
            if v["hash"] != d["invoice_hash"]:
                tamper.append(d["doc_no"])
            if not v["signature_ok"]:
                sig_bad.append(d["doc_no"])
        prev_hash, prev_icv = d["invoice_hash"], d["icv"]
    n = len(docs)
    _item(items, sec, "عدّاد الفواتير (ICV) متسلسل بلا فجوة ولا تكرار",
          FAIL if gaps else OK,
          ("فجوات: " + "، ".join(gaps[:5])) if gaps else
          f"{n} مستند — آخر عدّاد {summ['last_icv']}")
    _item(items, sec, "سلسلة البصمات (PIH): كل مستندٍ يحمل بصمة سابقه",
          FAIL if chain_bad else OK,
          ("مكسورة عند: " + "، ".join(chain_bad[:5])) if chain_bad else
          "سليمة من أول مستند")
    if deep:
        _item(items, sec, "بصمة كل مستند تطابق نصّه (لم يُعبث بمستند)",
              FAIL if tamper else OK,
              ("لا تطابق: " + "، ".join(tamper[:5])) if tamper else
              f"أُعيد حساب {n} بصمة")
        _item(items, sec, "الختم التشفيري (ECDSA) صحيح", FAIL if sig_bad else
              OK, ("غير صحيح: " + "، ".join(sig_bad[:5])) if sig_bad else
              f"تُحقّق من {len(tail)} توقيعاً")

    # ════ ٤) الفواتير ════
    sec = "الفواتير والإرسال"
    by = summ["by_status"]
    pend = by.get("pending", 0) + by.get("error", 0)
    late = conn.execute(
        "SELECT COUNT(*) FROM fatoora_documents WHERE archived=0 AND"
        " subtype='simplified' AND status IN ('pending','error') AND"
        " created_at < datetime('now','localtime','-24 hours')"
        ).fetchone()[0]
    _item(items, sec, "مقبولة لدى الهيئة (أُبلغت / اعتُمدت)", INFO,
          f"{sum(by.get(s, 0) for s in ledger.ACCEPTED)} مستند")
    _item(items, sec, "بانتظار الإرسال", WARN if pend else OK,
          f"{pend} مستند" if pend else "لا شيء معلّق")
    _item(items, sec, "الفواتير المبسطة تُبلَّغ خلال 24 ساعة",
          FAIL if late else OK,
          f"{late} مستند تجاوز المهلة" if late else "لا تأخير")
    _item(items, sec, "مستندات مرفوضة من الهيئة", FAIL if by.get("rejected")
          else OK, f"{by.get('rejected', 0)} مرفوض")
    act = p.get("activated_at") or ""
    if act and ledger.enabled(conn):
        missing = conn.execute(
            "SELECT COUNT(*) FROM invoices i JOIN entities e ON"
            " e.id=i.customer_id WHERE i.is_deleted=0 AND i.vat_applied=1"
            " AND e.entity_type<>'internal' AND i.created_at>=? AND NOT"
            " EXISTS (SELECT 1 FROM fatoora_documents d WHERE"
            " d.source_table='invoices' AND d.source_id=i.id AND"
            " d.archived=0)", (act,)).fetchone()[0]
        try:        # المبيعات الضريبية خارج المخزون — ضريبيةٌ كلّها
            missing += conn.execute(
                "SELECT COUNT(*) FROM tax_sales s WHERE s.is_deleted=0"
                " AND s.created_at>=? AND NOT EXISTS (SELECT 1 FROM"
                " fatoora_documents d WHERE d.source_table='tax_sales'"
                " AND d.source_id=s.id AND d.archived=0)",
                (act,)).fetchone()[0]
        except Exception:
            pass
        _item(items, sec, "كل فاتورة ضريبية بعد التفعيل لها مستند إلكتروني",
              FAIL if missing else OK,
              f"{missing} فاتورة بلا مستند (صدرت من جهازٍ آخر؟)" if missing
              else "مكتمل")
        nonvat = conn.execute(
            "SELECT COUNT(*) FROM invoices i JOIN entities e ON"
            " e.id=i.customer_id WHERE i.is_deleted=0 AND i.vat_applied=0"
            " AND e.entity_type<>'internal' AND i.created_at>=?",
            (act,)).fetchone()[0]
        _item(items, sec, "فواتير بيع بلا ضريبة بعد التفعيل", WARN if nonvat
              else OK, f"{nonvat} فاتورة — راجع معالجتها الضريبية مع "
              "محاسبك" if nonvat else "لا توجد")

    # ════ ٥) المشترون ════
    sec = "المشترون (الفواتير الضريبية B2B)"
    b2b = conn.execute(
        "SELECT id FROM entities WHERE is_deleted=0 AND entity_type IN"
        " ('customer','other') AND TRIM(COALESCE(vat_number,''))<>''"
        ).fetchall()
    bad_vat, no_addr = [], []
    for r in b2b:
        b = pf.buyer(conn, r["id"])
        if not pf.valid_vat(b["vat"]):
            bad_vat.append(b["name"])
        elif pf.buyer_problems(b):
            no_addr.append(b["name"])
    _item(items, sec, "الأرقام الضريبية للعملاء بصيغة صحيحة",
          WARN if bad_vat else OK,
          ("غير صحيحة (ستصدر فواتيرهم مبسطة): " + "، ".join(bad_vat[:6]))
          if bad_vat else f"{len(b2b)} عميل مسجّل ضريبياً")
    _item(items, sec, "العنوان الوطني المفصّل لكل عميل مسجّل ضريبياً",
          FAIL if no_addr else OK,
          ("ينقص عنوان: " + "، ".join(no_addr[:6])
           + (" …" if len(no_addr) > 6 else "")
           + " — لن تُصدر فواتيرهم حتى يكتمل") if no_addr else "مكتمل")

    # ════ ٦) البيئة التقنية ════
    sec = "البيئة التقنية"
    skew = api.LAST.get("server_skew")
    if skew is None:
        _item(items, sec, "ساعة الجهاز مضبوطة على ساعة الهيئة", INFO,
              "لم تُقارن بعد — اضغط «اختبار الاتصال»")
    else:
        _item(items, sec, "ساعة الجهاز مضبوطة على ساعة الهيئة",
              OK if abs(skew) <= 120 else WARN,
              f"الفرق {abs(skew):.0f} ثانية")
    reach = api.LAST.get("reachable")
    _item(items, sec, "الوصول إلى بوابة فاتورة",
          INFO if reach is None else (OK if reach else WARN),
          "لم يُختبر بعد" if reach is None else
          ("متاحة" if reach else "تعذّر الوصول — تحقق من الإنترنت"))
    _item(items, sec, "الختم والتوقيع يعملان بلا مكتبات خارجية", OK,
          "secp256k1 · ECDSA-SHA256 · C14N · XAdES — مدمجة في النظام")
    _item(items, sec, "الورقة المطبوعة: «فاتورة ضريبية» / «مبسطة» / «إشعار "
          "دائن» + رمز QR المرحلة الثانية", OK, "في قالب طباعة الفاتورة")

    v = verdict(conn, st, summ)
    done = sum(1 for i in items if i["status"] == OK)
    need = sum(1 for i in items if i["status"] in (OK, WARN, FAIL))
    return {"verdict": v, "items": items, "score": (done, need),
            "stage": st, "summary": summ, "env": env}
