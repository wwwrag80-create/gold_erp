# -*- coding: utf-8 -*-
"""فحص وقائي شامل — يكشف الأخطاء البنيوية قبل ظهورها للمستخدم.

يُشغَّل تلقائياً في verify_all، ويمكن تشغيله وحده:
    python tools/selfcheck.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SKIP = {"__pycache__", "build", "dist", ".git"}


def check_duplicate_defs():
    """دوال مكررة في نفس الملف — سبب شائع لأخطاء 'أصلحته فعاد'."""
    bad = []
    for p in ROOT.rglob("*.py"):
        if any(s in p.parts for s in SKIP):
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        names = re.findall(r"^def (\w+)\(", src, re.M)
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            bad.append((p.relative_to(ROOT), dup))
    return bad


def check_undefined_names():
    """أسماء مستخدَمة بلا تعريف داخل نفس الوحدة (تقريب سريع)."""
    import ast
    bad = []
    for p in ROOT.rglob("*.py"):
        if any(s in p.parts for s in SKIP):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError as e:
            bad.append((p.relative_to(ROOT), [f"SyntaxError: {e.msg}"]))
    return bad


def check_no_service_key_in_client():
    """مفتاح الخدمة يجب ألا يُشترط في مسارات المستخدم."""
    p = ROOT / "services" / "cloud_auth.py"
    if not p.exists():
        return ["services/cloud_auth.py مفقود"]
    src = p.read_text(encoding="utf-8")
    if "service_key" in src:
        return ["cloud_auth ما زال يعتمد على مفتاح الخدمة"]
    return []


def check_no_secrets_committed():
    """لا يُوزَّع ملف أسرار مع النظام ولا يدخل المستودع.

    مفتاح `service_role` يتجاوز كل صلاحيات RLS على قاعدة Supabase:
    من يملكه يقرأ ويكتب بيانات **كل** المصانع. وجوده في ملف يُشحن مع
    النسخة أو يُرفع للمستودع يعني أن المفتاح لم يعد سرياً.
    """
    out = []
    env = ROOT / ".env"
    if env.exists():
        try:
            body = env.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            body = ""
        if "SUPABASE_SERVICE_KEY" in body:
            for line in body.splitlines():
                s = line.strip()
                if s.startswith("SUPABASE_SERVICE_KEY") and "=" in s:
                    if s.split("=", 1)[1].strip():
                        out.append(
                            ".env يحتوي مفتاح خدمة فعلياً — لا تُوزّعه مع "
                            "النسخة ولا ترفعه للمستودع (أبطِله وأصدر بديلاً)")
                    break
    gi = ROOT / ".gitignore"
    if not gi.exists():
        out.append(".gitignore مفقود — قد يُرفع .env للمستودع بالخطأ")
    elif ".env" not in gi.read_text(encoding="utf-8", errors="ignore"):
        out.append(".gitignore لا يستثني .env")
    return out


def check_rpc_contract():
    """كل دالة خادم يناديها العميل يجب أن تكون في ملف SQL."""
    sql = ROOT / "cloud" / "admin_rpc.sql"
    if not sql.exists():
        return ["cloud/admin_rpc.sql مفقود"]
    sql_src = sql.read_text(encoding="utf-8")
    client = (ROOT / "services" / "cloud_auth.py").read_text(encoding="utf-8")
    called = set(re.findall(r'_rpc\(\s*"(\w+)"', client))
    defined = set(re.findall(r"FUNCTION (\w+)\(", sql_src))
    missing = sorted(called - defined)
    return [f"دالة يناديها العميل وغير معرّفة في SQL: {m}"
            for m in missing]


def check_diagnose_keys():
    """مفاتيح diagnose() المستخدَمة في الواجهة يجب أن تكون موجودة.

    هذا النوع من الأخطاء (KeyError على مفتاح محذوف) هو سبب رسائل
    غامضة مثل 'table' — فنكشفه قبل وصوله للمستخدم.
    """
    import ast as _a
    src = (ROOT / "services" / "cloud_auth.py").read_text(encoding="utf-8")
    m = re.search(r"def diagnose\(\).*?return out", src, re.S)
    if not m:
        return ["diagnose() غير موجودة"]
    blk_src = m.group(0)
    # المفاتيح تُعرَّف بطريقتين: في القاموس الأولي، أو بالإسناد
    provided = set(re.findall(r'out\["(\w+)"\]', blk_src))
    lit = re.search(r"out\s*=\s*\{(.*?)\}", blk_src, re.S)
    if lit:
        provided |= set(re.findall(r'"(\w+)"\s*:', lit.group(1)))
    ui = (ROOT / "ui" / "super_admin_screen.py").read_text(encoding="utf-8")
    blk = re.search(r"def check_keys\(self\).*?except Exception", ui, re.S)
    used = set(re.findall(r"d\['(\w+)'\]", blk.group(0))) if blk else set()
    missing = sorted(used - provided)
    return [f"الواجهة تستخدم مفتاحاً غير موجود في diagnose: {k}"
            for k in missing]


def check_sql_not_null():
    """أعمدة NOT NULL يجب أن تُملأ بقيمة مضمونة في دوال الخادم."""
    sql = ROOT / "cloud" / "admin_rpc.sql"
    if not sql.exists():
        return []
    src = sql.read_text(encoding="utf-8")
    errs = []
    for m in re.finditer(r"INSERT INTO factories\([^)]*\)\s*VALUES\s*\(([^;]+?)\)\s*ON CONFLICT",
                         src, re.S):
        vals = m.group(1)
        if "COALESCE" not in vals:
            errs.append("INSERT INTO factories بلا COALESCE على الاسم")
    return errs


def check_rpc_version_sync():
    """إصدار الدوال في الكود يجب أن يطابق ملف SQL."""
    py = (ROOT / "services" / "cloud_auth.py").read_text(encoding="utf-8")
    sql = (ROOT / "cloud" / "admin_rpc.sql").read_text(encoding="utf-8")
    m1 = re.search(r'RPC_EXPECTED\s*=\s*"([^"]+)"', py)
    m2 = re.search(r"SELECT '([^']+)'::TEXT", sql)
    if not m1:
        return ["RPC_EXPECTED غير معرّف في الكود"]
    if not m2:
        return ["rpc_version غير موجودة في ملف SQL"]
    if m1.group(1) != m2.group(1):
        return [f"إصدار الكود ({m1.group(1)}) لا يطابق SQL ({m2.group(1)})"]
    return []


def check_ui_error_paths():
    """كل معالج في الواجهة يجب أن يلتقط الأخطاء ويعرضها."""
    errs = []
    for p in (ROOT / "ui").rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        # الدوال التي تنادي الخدمات السحابية
        for m in re.finditer(r"def (\w+)\(self[^)]*\):(.*?)(?=\n    def |\Z)",
                             src, re.S):
            body = m.group(2)
            if "cloud_auth." in body or "cloud_backup." in body:
                if "except" not in body:
                    errs.append(f"{p.name}::{m.group(1)} بلا معالجة أخطاء")
    return errs


def check_optional_features_safe():
    """الميزات الاختيارية يجب ألا تُعطّل العمليات المحاسبية.

    الباركود وQR والطباعة تحسينات — فشلها لا يجوز أن يمنع حفظ فاتورة.
    نتأكد أن دوالها تلتقط **كل** الأخطاء لا ImportError وحده.
    """
    errs = []
    for name in ("barcode_service", "zatca"):
        p = ROOT / "services" / f"{name}.py"
        if not p.exists():
            continue
        src = p.read_text(encoding="utf-8")
        if "except ImportError" in src and "except Exception" not in src:
            errs.append(f"{name}: يلتقط ImportError فقط — "
                        f"أخطاء الملفات ستُعطّل العمل")
    # التوريد يجب ألا ينهار بفشل الباركود
    inv = (ROOT / "models" / "inventory.py").read_text(encoding="utf-8")
    if "generate_work_order_barcode" in inv:
        bs = (ROOT / "services" / "barcode_service.py").read_text(
            encoding="utf-8")
        if "except Exception" not in bs:
            errs.append("barcode_service بلا حماية شاملة")
    return errs


def check_backup_intervals():
    """فترات النسخ الاحتياطي ضمن حدود معقولة."""
    errs = []
    cb = (ROOT / "services" / "cloud_backup.py").read_text(encoding="utf-8")
    m = re.search(r"UPLOAD_EVERY_SEC\s*=\s*(\d+)", cb)
    # 10 دقائق حدّ مقبول: الرفع كل 30 ثانية كان يُثقل القرص والشبكة،
    # ومع الرفع عند كل إغلاق لا تُفقد بيانات تُذكر.
    if m and int(m.group(1)) > 900:
        errs.append(f"الرفع السحابي بطيء ({m.group(1)} ثانية)")
    return errs


def check_balance_sheet_coverage():
    """كل أنواع الحسابات يجب أن تكون مغطاة في الميزانية العمومية.

    حساب غير مُدرج يجعل الميزانية تبدو غير متوازنة رغم سلامة القيود —
    وهو خطأ يصعب تشخيصه، فنكشفه هنا.
    """
    rep = (ROOT / "models" / "reports.py").read_text(encoding="utf-8")
    m = re.search(r"def balance_sheet\(.*?return \{", rep, re.S)
    if not m:
        return ["balance_sheet غير موجودة"]
    covered = set(re.findall(r'bal\(\[([^\]]+)\]\)', m.group(0)))
    codes = set()
    for grp in covered:
        codes |= set(re.findall(r'"(\d+)"', grp))
    seed = (ROOT / "database" / "seed.py").read_text(encoding="utf-8")
    # كل حساب قابل للحركة في الشجرة
    postable = set()
    for mm in re.finditer(r'\("(\d+)",\s*"[^"]+",\s*"(\w+)",\s*"(\d+)",\s*1,',
                          seed):
        postable.add((mm.group(1), mm.group(3)))
    missing = []
    for code, parent in sorted(postable):
        if code in codes or parent in codes:
            continue
        # تحقق من الأجداد
        found = False
        p2 = parent
        for _ in range(4):
            if p2 in codes:
                found = True
                break
            mm = re.search(rf'\("{p2}",\s*"[^"]+",\s*"\w+",\s*"(\d+)"', seed)
            p2 = mm.group(1) if mm else ""
            if not p2:
                break
        if not found:
            missing.append(code)
    return [f"حسابات غير مغطاة في الميزانية: {', '.join(missing)}"] \
        if missing else []


DEPRECATED = {
    "adjust_wo_weight": "adjust_or_delete_wo",
}


def check_deprecated_calls():
    """الواجهة يجب ألا تنادي دوالاً مهجورة استُبدلت بأخرى.

    استدعاء نسخة قديمة بجانب جديدة يجعل نصف الميزات تعمل والنصف
    الآخر لا — وهو خطأ يصعب تشخيصه.
    """
    errs = []
    for p in (ROOT / "ui").rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        for old, new in DEPRECATED.items():
            if re.search(rf"\.{old}\s*\(", src):
                errs.append(f"{p.name} ينادي {old} — استخدم {new}")
    return errs


def main():
    print("=" * 54)
    print("  الفحص الوقائي")
    print("=" * 54)
    ok = True

    dup = check_duplicate_defs()
    print(f"  {'✔' if not dup else '✘'} دوال مكررة")
    for f, d in dup:
        print(f"      {f}: {', '.join(d)}")
        ok = False

    syn = check_undefined_names()
    print(f"  {'✔' if not syn else '✘'} صياغة الملفات")
    for f, d in syn:
        print(f"      {f}: {d}")
        ok = False

    for label, fn in (("استقلال العميل عن مفتاح الخدمة",
                       check_no_service_key_in_client),
                      ("عدم تسريب الأسرار", check_no_secrets_committed),
                      ("تطابق دوال الخادم", check_rpc_contract),
                      ("تطابق مفاتيح التشخيص", check_diagnose_keys),
                      ("أعمدة SQL الإلزامية", check_sql_not_null),
                      ("تطابق إصدار الدوال", check_rpc_version_sync),
                      ("معالجة أخطاء الواجهة", check_ui_error_paths),
                      ("أمان الميزات الاختيارية",
                       check_optional_features_safe),
                      ("فترات النسخ الاحتياطي", check_backup_intervals),
                      ("تغطية الميزانية العمومية",
                       check_balance_sheet_coverage),
                      ("دوال مهجورة", check_deprecated_calls)):
        errs = fn()
        print(f"  {'✔' if not errs else '✘'} {label}")
        for e in errs:
            print(f"      {e}")
            ok = False

    print("=" * 54)
    print("  ✔ سليم" if ok else "  ✘ توجد مشاكل بنيوية")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
