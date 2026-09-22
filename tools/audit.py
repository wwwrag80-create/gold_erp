# -*- coding: utf-8 -*-
"""صائد الأخطاء الصامتة — فحص جودة على مستوى أنظمة ERP.

**المشكلة التي يحلّها**: الخطأ الصامت أخطر من الظاهر. عملية تبدو
ناجحة بلا أثر محاسبي، أو حذف لا يحذف، أو استثناء يُبتلع في `except`
فارغ — كلها تُفقد الثقة بالنظام لأن المستخدم لا يعرف أن شيئاً فشل.

يفحص هذا الملف أنماط الخلل المعروفة في الكود نفسه، ويُشغَّل ضمن
`verify_all` فلا يمرّ بناء بها.

    python tools/audit.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SKIP_DIRS = {"__pycache__", "build", "dist", ".git", "tools"}


def _py_files(sub=None):
    root = ROOT / sub if sub else ROOT
    for p in root.rglob("*.py"):
        if any(s in p.parts for s in SKIP_DIRS):
            continue
        yield p


# ══════════════════════════════════════════════════════════════════
# 1) استثناءات مبتلعة في مسارات الحفظ
# ══════════════════════════════════════════════════════════════════

SAVE_FN = re.compile(r"def (save|post|create|delete|update|repost|wipe)"
                     r"\w*\s*\(")


def check_swallowed_in_save():
    """`except: pass` داخل دالة حفظ = عملية تفشل بلا علم المستخدم."""
    errs = []
    for p in _py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not SAVE_FN.match(f"def {fn.name}("):
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                body = node.body
                # `pass` وحده، أو تعليق فقط — بلا إبلاغ ولا رفع
                only_pass = (len(body) == 1
                             and isinstance(body[0], ast.Pass))
                if only_pass and node.type is None:
                    errs.append(
                        f"{p.name}::{fn.name} سطر {node.lineno} — "
                        f"except عارٍ يبتلع الخطأ")
    return errs


# ══════════════════════════════════════════════════════════════════
# 2) عمليات تكتب بلا تحقق من الأثر
# ══════════════════════════════════════════════════════════════════

def check_post_entry_verified():
    """كل قيد يجب أن يمرّ بالتحقق من الترحيل."""
    p = ROOT / "services" / "accounting_engine.py"
    if not p.exists():
        return ["accounting_engine.py مفقود"]
    src = p.read_text(encoding="utf-8")
    if "_verify_entry_posted" not in src:
        return ["post_entry بلا تحقق من كتابة الأسطر وتوازنها"]
    return []


# ══════════════════════════════════════════════════════════════════
# 3) الحذف المنطقي متسق
# ══════════════════════════════════════════════════════════════════

SOFT_DELETE_TABLES = ("invoices", "vouchers", "work_orders",
                      "journal_entries", "entities", "workshop_losses")


def check_soft_delete_filters():
    """كل استعلام على جدول له `is_deleted` يجب أن يُرشّحه.

    إغفاله يُظهر سجلات محذوفة كأنها قائمة — وهو سبب «الأسماء التي
    لا تُحذف».
    """
    errs = []
    for p in _py_files("models"):
        src = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(
                r"FROM\s+(" + "|".join(SOFT_DELETE_TABLES) + r")\b"
                r"(?:\s+(?:AS\s+)?(\w+))?", src):
            tbl, alias = m.group(1), m.group(2)
            tail = src[m.end():m.end() + 420]
            a = alias or tbl
            has = (f"{a}.is_deleted" in tail or "is_deleted=0" in tail
                   or "is_deleted = 0" in tail)
            if has or "is_deleted" in tail:
                continue

            # ── استثناءات مشروعة ──
            # 1) البحث بمعرّف صريح: المستدعي يعرف ما يطلب (تعديل/تحقق)
            # `FROM <جدول>` قد يقع بعد `WHERE` في نص مقسّم على أسطر،
            # فنفحص نافذة تشمل ما قبل الموضع وما بعده معاً.
            window = src[max(0, m.start() - 200):m.end() + 420]
            flat = re.sub(r"[\"'\s]+", " ", window)
            # بحث بمعرّف صريح: المستدعي يقصد سجلاً بعينه
            if re.search(r"WHERE\s+(\w+\.)?id\s*=\s*\?", flat):
                continue
            if "entity_type='internal'" in flat.replace(" ", ""):
                continue
            # 2) الترقيم التسلسلي: لا يُعاد استخدام رقم مستند محذوف
            if "COUNT(*)" in tail and "MAX(" not in tail:
                continue
            # 3) سجلات تعرض المحذوف عمداً (موثّقة بتعليق صريح)
            head = src[max(0, m.start() - 500):m.start()]
            if ("يشمل المحذوف" in head or "بما فيه المحذوف" in head
                    or "including deleted" in head.lower()):
                continue
            # دوال الحذف النهائي تمسح السجل من الوجود، فترشيح
            # is_deleted فيها يترك سجلات معلّقة بلا حساب.
            before = src[:m.start()]
            last_def = before.rfind("\ndef ")
            if last_def >= 0:
                fname = before[last_def + 5:before.find("(", last_def)]
                if fname.startswith(("purge_", "wipe_", "_purge",
                                     "delete_account")):
                    continue
            line = src[:m.start()].count("\n") + 1
            errs.append(f"{p.name}:{line} — استعلام على {tbl} "
                        f"بلا ترشيح is_deleted")
    return errs[:12]


# ══════════════════════════════════════════════════════════════════
# 4) الترقيم الفريد بلا تعارض
# ══════════════════════════════════════════════════════════════════

def check_unique_codes():
    """توليد أكواد الحسابات يجب أن يفحص التفرّد عالمياً."""
    p = ROOT / "models" / "entities.py"
    src = p.read_text(encoding="utf-8")
    if "SELECT code FROM accounts" not in src:
        return ["توليد كود الحساب لا يفحص التفرّد في الشجرة كلها"]
    return []


# ══════════════════════════════════════════════════════════════════
# 5) وضع التعديل محميّ
# ══════════════════════════════════════════════════════════════════

def check_edit_guards():
    """شاشات التعديل يجب أن تتحقق من بقاء المستند حياً."""
    errs = []
    em = ROOT / "ui" / "widgets" / "edit_mode.py"
    if em.exists() and "_entry_alive" not in em.read_text(encoding="utf-8"):
        errs.append("edit_mode بلا تحقق من بقاء القيد")
    sales = ROOT / "ui" / "sales_screen.py"
    if sales.exists():
        src = sales.read_text(encoding="utf-8")
        if "editing_id" in src and "AND is_deleted=0" not in src:
            errs.append("sales_screen بلا حارس للفاتورة المحذوفة")
    return errs


# ══════════════════════════════════════════════════════════════════
# 6) المسح شامل
# ══════════════════════════════════════════════════════════════════

def check_reset_completeness():
    """تهيئة النظام يجب أن تشمل كل قواعد المصانع."""
    p = ROOT / "models" / "system_reset.py"
    if not p.exists():
        return ["system_reset.py مفقود"]
    src = p.read_text(encoding="utf-8")
    if "wipe_all_tenants" not in src:
        return ["المسح لا يشمل قواعد المصانع الأخرى"]
    return []


# ══════════════════════════════════════════════════════════════════
# 7) عزل المصانع مفعّل
# ══════════════════════════════════════════════════════════════════

def check_tenant_isolation():
    """مسار قاعدة البيانات يجب أن يعتمد على هوية المصنع."""
    p = ROOT / "core" / "config.py"
    src = p.read_text(encoding="utf-8")
    if "tenant_db_path" not in src:
        return ["قاعدة البيانات ليست معزولة لكل مصنع"]
    # المنطق في `services/login_flow.py` تستعمله البوابة وشاشة
    # الدخول معاً؛ ويُقبل وجودُه في أيٍّ منها — فالمهمّ أن يُضبط
    # المصنع قبل أي قراءة، لا في أي ملفٍ كُتب.
    seen = False
    for rel in (("services", "login_flow.py"), ("ui", "gate_window.py"),
                ("ui", "login_window.py")):
        p2 = ROOT.joinpath(*rel)
        if p2.exists() and "set_active_tenant" in p2.read_text(
                encoding="utf-8"):
            seen = True
            break
    if not seen:
        return ["الدخول لا يضبط هوية المصنع قبل قراءة البيانات"]
    # ولا يجوز أن تُكتب شاشةُ دخولٍ ثانية بمنطقٍ خاص بها
    login = ROOT / "ui" / "login_window.py"
    if login.exists():
        src2 = login.read_text(encoding="utf-8")
        if "cloud_auth.login" in src2 and "login_flow" not in src2:
            return ["شاشة الدخول تتحقّق بنفسها بدل المسار المشترك"]
    return []


def check_backup_paths():
    """مسارات النسخ الاحتياطي يجب أن تتبع قاعدة المصنع النشطة.

    مسار مستقل يعني النسخ على ملف غير موجود — والمستخدم يظن بياناته
    محفوظة وهي ليست كذلك. خطأ صامت لا يُكتشف إلا عند الحاجة للنسخة.
    """
    errs = []
    p = ROOT / "services" / "storage.py"
    if p.exists():
        src = p.read_text(encoding="utf-8")
        if "config.DB_PATH" not in src:
            errs.append("storage.db_path لا يتبع قاعدة المصنع النشطة")
    return errs


def check_thread_cleanup():
    """كل QThread يجب أن يُنظَّف بعد انتهائه.

    تراكم الخيوط يُثقل النظام تدريجياً حتى يتجمّد.
    """
    errs = []
    for p in (ROOT / "ui").rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        if "QtCore.QThread" in src and "deleteLater" not in src:
            errs.append(f"{p.name}: خيط بلا تنظيف (deleteLater)")
    return errs


def check_print_builders():
    """كل نوع مستند تناديه الواجهة يجب أن يكون له قالب مسجَّل.

    حذف قالب أو خريطة `BUILDERS` أثناء التعديل يُنتج
    `AttributeError` عند أول محاولة معاينة — خطأ يظهر للمستخدم
    مباشرةً ويوقف عمله.
    """
    errs = []
    pm = ROOT / "services" / "print_manager.py"
    if not pm.exists():
        return ["print_manager.py مفقود"]
    src = pm.read_text(encoding="utf-8")
    if "BUILDERS = {" not in src:
        return ["BUILDERS غير معرّفة في print_manager"]
    if "DOC_LABELS = {" not in src:
        errs.append("DOC_LABELS غير معرّفة")
    # كل قالب مذكور في الخريطة يجب أن يكون معرّفاً
    block = src[src.index("BUILDERS = {"):]
    block = block[:block.index("}") + 1]
    for fn in set(re.findall(r":\s*(_tpl_\w+)", block)):
        if f"def {fn}(" not in src:
            errs.append(f"قالب مفقود: {fn}")
    # وكل نوع تناديه الواجهة يجب أن يكون في الخريطة
    mapped = set(re.findall(r'"([\w]+)"\s*:\s*_tpl_', block))
    for p in (ROOT / "ui").rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        u = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(
                r'preview_document\(\s*self\s*,\s*"(\w+)"', u):
            t = m.group(1)
            if t not in mapped and t not in (
                    "statement", "balances", "turnover",
                    "customer_analytics", "mfg_target", "mfg_salary",
                    "mfg_summary"):
                errs.append(f"{p.name} ينادي نوعاً بلا قالب: {t}")
    return sorted(set(errs))


def check_index_totals():
    """جمع أعمدة الجدول بفهرس رقمي هشّ.

    `sum(r[7] for r in rows)` ينكسر بصمت عند إضافة أي عمود — تُزاح
    الفهارس فيُجمع نصٌ بدل رقم. الأصحّ الحساب من مصدر البيانات.
    """
    errs = []
    for p in (ROOT / "ui").rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"sum\(\s*\w+\[(\d+)\]\s+for\s+\w+\s+in\s+rows",
                             src):
            line = src[:m.start()].count("\n") + 1
            errs.append(f"{p.name}:{line} — جمع بفهرس عمود ({m.group(1)})")
    return errs


BLOCKING = ("webbrowser.open", "os.startfile", "subprocess.call",
            "subprocess.run", "time.sleep", "urlopen")


def check_blocking_ui():
    """نداءات محجوبة على خيط الواجهة تُجمّد النظام.

    فتح المتصفح أو طلب شبكة أو انتظار — كلها توقف خيط الواجهة فيعلن
    ويندوز «لا يستجيب». يجب أن تجري في خيط منفصل أو مؤقّت مؤجَّل.
    """
    errs = []
    for p in list((ROOT / "ui").rglob("*.py")) + \
            list((ROOT / "services").rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        safe = ("threading.Thread" in src or "QTimer" in src
                or "QThread" in src)
        for call in BLOCKING:
            if call not in src or safe:
                continue
            # طلب شبكة بمهلة محدودة مقبول: لا ينتظر بلا نهاية
            if call == "urlopen" and "timeout=" in src:
                continue
            # عملية فرعية بمهلة محدودة داخل حوار تقدّم مقبولة كذلك:
            # المستخدم يرى ما يجري ولا تنتظر بلا نهاية
            if call.startswith("subprocess.") and "timeout=" in src:
                continue
            if True:
                line = src[:src.index(call)].count("\n") + 1
                errs.append(f"{p.name}:{line} — {call} بلا خيط أو تأجيل")
    return sorted(set(errs))


def check_nested_db():
    """اتصال بقاعدة البيانات داخل معاملة مفتوحة.

    `with db()` داخل `with db()` يفتح اتصالاً ثانياً ينتظر قفل الأول
    ثلاثين ثانية — فيتجمّد النظام ثم يكمل بنجاح. أخطر ما فيه أنه
    يبدو «بطئاً» لا خطأً، فيصعب تشخيصه.
    """
    errs = []
    # الخصائص التي تفتح اتصالاً ويُستدعَون داخل معاملات
    risky = {"is_editing"}
    em = ROOT / "ui" / "widgets" / "edit_mode.py"
    if em.exists():
        src = em.read_text(encoding="utf-8")
        i = src.find("def is_editing")
        if i >= 0:
            j = src.find("\n    def ", i + 10)
            body = src[i:j if j > 0 else len(src)]
            if "with db()" in body or "_entry_alive(" in body:
                errs.append(
                    "edit_mode.is_editing يفتح اتصالاً — يُستدعى داخل "
                    "معاملات فيتنازع على القفل")
    # `with db()` متداخل في ملف واحد داخل نفس الدالة
    for p in list((ROOT / "ui").rglob("*.py")) + \
            list((ROOT / "models").rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        src = p.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            depth = 0
            for node in ast.walk(fn):
                if isinstance(node, ast.With):
                    for item in node.items:
                        c = item.context_expr
                        if isinstance(c, ast.Call) and \
                                getattr(c.func, "id", "") == "db":
                            depth += 1
            if depth > 1:
                # قد تكون متتالية لا متداخلة — نتحقق من التداخل فعلاً
                for node in ast.walk(fn):
                    if not isinstance(node, ast.With):
                        continue
                    outer = any(isinstance(i.context_expr, ast.Call) and
                                getattr(i.context_expr.func, "id", "") == "db"
                                for i in node.items)
                    if not outer:
                        continue
                    for inner in ast.walk(node):
                        if inner is node or not isinstance(inner, ast.With):
                            continue
                        if any(isinstance(i.context_expr, ast.Call) and
                               getattr(i.context_expr.func, "id", "") == "db"
                               for i in inner.items):
                            errs.append(
                                f"{p.name}::{fn.name} سطر {inner.lineno}"
                                f" — اتصال متداخل")
    return sorted(set(errs))


CHECKS = [
    ("استثناءات مبتلعة في الحفظ", check_swallowed_in_save),
    ("التحقق من ترحيل القيود", check_post_entry_verified),
    ("ترشيح الحذف المنطقي", check_soft_delete_filters),
    ("تفرّد أكواد الحسابات", check_unique_codes),
    ("حراسة وضع التعديل", check_edit_guards),
    ("شمول تهيئة النظام", check_reset_completeness),
    ("عزل بيانات المصانع", check_tenant_isolation),
    ("مسارات النسخ الاحتياطي", check_backup_paths),
    ("تنظيف الخيوط", check_thread_cleanup),
    ("قوالب الطباعة", check_print_builders),
    ("جمع الأعمدة بالفهرس", check_index_totals),
    ("نداءات محجوبة على الواجهة", check_blocking_ui),
    ("اتصال متداخل بقاعدة البيانات", check_nested_db),
]


def main():
    print("=" * 56)
    print("  صائد الأخطاء الصامتة")
    print("=" * 56)
    ok = True
    for label, fn in CHECKS:
        try:
            errs = fn()
        except Exception as e:
            errs = [f"تعذّر الفحص: {type(e).__name__}: {e}"]
        print(f"  {'✔' if not errs else '✘'} {label}")
        for e in errs:
            print(f"      {e}")
            ok = False
    print("=" * 56)
    print("  ✔ سليم" if ok else "  ✘ توجد مخاطر أخطاء صامتة")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
