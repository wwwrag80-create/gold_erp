# -*- coding: utf-8 -*-
"""الحقل الرقمي الذكي — حاسبةٌ داخل كل خانة، والأرقام العربية مقبولة.

**حاسبة**: يكتب المستخدم «120+35.5» أو «3*12.5» أو «(40-2.5)/2» في أي
خانة وزنٍ أو مبلغ، فتصير النتيجة عند Enter أو مغادرة الخانة. كان يفتح
الآلة الحاسبة ليجمع ثلاثة أوزان ثم ينقل الناتج بيده — وكل نقلٍ فرصة
خطأ.

**الأرقام العربية**: من يكتب بلوحة مفاتيح عربية تخرج أرقامه «١٢٫٥» —
فكانت الخانة ترفضها بصمت ولا يُكتب فيها شيء. الآن تُقبل وتُحوَّل فوراً
إلى «12.5»، فالنظام يعرض أرقامه بالإنجليزية في كل مكان.

**الأمان**: التقييم بشجرة التعبير (`ast`) لا بـ`eval`: أرقامٌ و+ − × ÷
وأقواس فقط. أي شيء آخر يُرفض — فلا يُنفَّذ نصٌّ يُلصق في الخانة.
"""
import ast
import operator
import re

_DIGITS = str.maketrans({
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٫": ".", "٬": ",", "،": ",", "×": "*", "÷": "/", "−": "-",
    "x": "*", "X": "*",
})

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv}
_EXPR_CHARS = re.compile(r"^[0-9.+\-*/() ]*$")
_HAS_OP = re.compile(r"[0-9.)]\s*[+\-*/]|[*/(]")


def normalize(text):
    """الأرقام العربية والهندية ← إنجليزية، و× ÷ ← * /."""
    return str(text or "").translate(_DIGITS)


def is_expression(text):
    """هل النصّ عمليةٌ حسابية (لا رقماً مجرّداً)؟"""
    t = normalize(text).replace(",", "").strip()
    return bool(t) and bool(_EXPR_CHARS.match(t)) and bool(_HAS_OP.search(t))


def _ev(node):
    if isinstance(node, ast.Expression):
        return _ev(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        # سلسلةٌ طويلة «12+15+9+…» شجرةٌ مائلةٌ لليسار بعمق عدد الأرقام —
        # تُمشى بحلقةٍ لا بعَوْدٍ، فلا يقف التقييم عند حدّ العمق في Python
        chain = []
        while isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            chain.append((node.op, node.right))
            node = node.left
        acc = _ev(node)
        for op, right in reversed(chain):
            acc = _OPS[type(op)](acc, _ev(right))
        return acc
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd,
                                                              ast.USub)):
        v = _ev(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    raise ValueError("غير مسموح")


def evaluate(text):
    """ناتج العملية الحسابية — أو None إن لم تكن عمليةً صحيحة كاملة."""
    t = normalize(text).replace(",", "").strip()
    # حدٌّ واسع: من يجمع أوزان دفعةٍ كاملة يكتب عشرات الأرقام (كان 120
    # حرفاً — فتُرفض السلسلة الطويلة بصمت ويبقى الرقم القديم)
    if not t or not _EXPR_CHARS.match(t) or len(t) > 20000:
        return None
    try:
        v = _ev(ast.parse(t, mode="eval"))
    except (SyntaxError, ValueError, ZeroDivisionError, TypeError,
            RecursionError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v
