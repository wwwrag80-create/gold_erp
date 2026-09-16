# -*- coding: utf-8 -*-
"""جداول احترافية — فرزٌ بالنقر، صفُّ إجماليٍّ ثابت، وتصدير بزر واحد.

**ثلاث حاجات يوميّة في كل نظام محاسبي**، كانت ناقصة هنا:

1. **الفرز بالنقر على العنوان**. وفرز Qt الجاهز يفرز نصّاً، فيجعل
   «١٠٠» قبل «٩» لأن المقارنة حرفٌ بحرف. الفرز هنا يقرأ الرقم من
   الخلية (بفواصل الآلاف وإشارة السالب والنسبة) ويفرز به، ويفرز
   التواريخ بترتيبها الزمني، وما عداه نصّاً بتطبيع عربي.

2. **صفُّ الإجمالي لا يُفرَز**. الإجمالي ليس صفَّ بيانات بل خلاصة ما
   فوقه؛ لو دخل الفرز لطفا إلى وسط الجدول فصار رقماً بين الأرقام.
   هنا يبقى في قاعه دائماً مهما فُرز ما فوقه.

3. **التصدير**. المحاسب يُسأل عن كشفٍ بصيغة Excel، فينسخ الجدول
   يدوياً خلية خلية. زرٌّ واحد ينسخه ملفاً بترميز يفتحه Excel العربي
   بلا حروف مشوّهة (BOM) — فالأرقام تبقى أرقاماً والعربية عربية.

**وعروض الأعمدة تُحفظ**: من يوسّع عمود «البيان» يجده موسَّعاً غداً.
تُحفظ نِسَباً لا بكسلات، فتصلح للشاشة الصغيرة والكبيرة معاً.
"""
import csv
import datetime as _dt
import re

from PyQt5 import QtCore, QtGui, QtWidgets

from ui.widgets.common import _norm, err, info, load_pref, save_pref

TOTAL_ROLE = QtCore.Qt.UserRole + 77       # وسم صف الإجمالي
_NUM = re.compile(r"^[\s+\-–—]*[\d,٫٬.]+\s*%?$")


def as_number(text):
    """الرقم داخل نص الخلية، أو None إن لم يكن رقماً.

    يقبل فواصل الآلاف وعلامة النسبة والسالب بالشرطة الطويلة (وهي ما
    تُنتجه بعض التقارير)، فلا يسقط عمودٌ من الفرز لعلامةٍ تجميلية.
    """
    t = (text or "").strip()
    if not t or not _NUM.match(t):
        return None
    t = (t.replace(",", "").replace("٬", "").replace("٫", ".")
         .replace("%", "").replace("–", "-").replace("—", "-").strip())
    try:
        return float(t)
    except ValueError:
        return None


def as_date(text):
    """تاريخ ISO داخل نص الخلية، أو None."""
    t = (text or "").strip()[:10]
    if len(t) != 10 or t[4] != "-" or t[7] != "-":
        return None
    try:
        return _dt.date.fromisoformat(t)
    except ValueError:
        return None


def _key(text):
    """مفتاح فرزٍ موحّد: الأرقام قبل التواريخ قبل النصوص.

    القيمة المعادة زوجٌ (رتبة النوع، القيمة) فلا تُقارَن قيمتان من
    نوعين مختلفين — وهو ما كان يرفع `TypeError` على عمود فيه أرقام
    وشرطات معاً.
    """
    n = as_number(text)
    if n is not None:
        return (0, n)
    d = as_date(text)
    if d is not None:
        return (1, d.toordinal())
    return (2, _norm(text))


# ══════════════════════════════════════════════════════════════════
#  الفرز
# ══════════════════════════════════════════════════════════════════

class Sorter(QtCore.QObject):
    """فرزٌ بالنقر يحترم صفَّ الإجمالي ويحافظ على بيانات الخلايا.

    فرزُ Qt الداخلي (`setSortingEnabled`) معطَّل في كل جداول النظام
    لأن `fill()` تُعيد بناء الصفوف؛ وهذا الفرز يعيد ترتيب الصفوف
    بنفسه بأخذ عناصرها كما هي — فتُحفظ بيانات كل خلية (`UserRole`)
    التي تعتمد عليها شاشات التعمّق، ولا تُفقد بإعادة إنشاء نصّية.
    """

    def __init__(self, table):
        super().__init__(table)
        self.table = table
        self.col = -1
        self.desc = False
        try:
            hh = table.horizontalHeader()
            hh.setSectionsClickable(True)
            hh.sectionClicked.connect(self.sort_by)
        except Exception:
            pass

    def _footer(self):
        """صفوف الإجمالي المثبَّتة في القاع (عادةً صفر أو واحد)."""
        t = self.table
        out = []
        for r in range(t.rowCount()):
            it = t.item(r, 0)
            if it is not None and it.data(TOTAL_ROLE):
                out.append(r)
        return out

    def sort_by(self, col):
        t = self.table
        if col < 0 or col >= t.columnCount() or t.rowCount() < 2:
            return
        self.desc = (not self.desc) if col == self.col else False
        self.col = col
        foot = set(self._footer())
        body = [r for r in range(t.rowCount()) if r not in foot]
        cells = {r: [t.takeItem(r, c) for c in range(t.columnCount())]
                 for r in range(t.rowCount())}
        body.sort(key=lambda r: _key(
            cells[r][col].text() if cells[r][col] is not None else ""),
            reverse=self.desc)
        order = body + sorted(foot)
        t.setUpdatesEnabled(False)
        try:
            for new_r, old_r in enumerate(order):
                for c, it in enumerate(cells[old_r]):
                    if it is not None:
                        t.setItem(new_r, c, it)
        finally:
            t.setUpdatesEnabled(True)
        try:
            t.horizontalHeader().setSortIndicator(
                col, QtCore.Qt.DescendingOrder if self.desc
                else QtCore.Qt.AscendingOrder)
            t.horizontalHeader().setSortIndicatorShown(True)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
#  صف الإجمالي
# ══════════════════════════════════════════════════════════════════

def total_row(table, values, label="الإجمالي"):
    """يضيف صفَّ إجماليٍّ مثبَّتاً في قاع الجدول.

    `values` قاموس {رقم العمود: القيمة} — وما لم يُذكر يُترك فارغاً.
    الصف موسومٌ فلا يفرزه `Sorter` ولا يُصدَّر مرتين.
    """
    r = table.rowCount()
    table.insertRow(r)
    f = QtGui.QFont(table.font())
    f.setBold(True)
    for c in range(table.columnCount()):
        v = values.get(c, "")
        if isinstance(v, float):
            v = f"{v:,.2f}".rstrip("0").rstrip(".")
        it = QtWidgets.QTableWidgetItem(label if c == 0 and not v
                                        else ("" if v is None else str(v)))
        it.setFont(f)
        if c == 0:
            it.setData(TOTAL_ROLE, True)
        table.setItem(r, c, it)
    return r


def sum_columns(table, cols):
    """مجموع أعمدةٍ من الجدول المعروض — بلا صفوف الإجمالي.

    الجمع من المعروض لا من المصدر مقصود: ما يراه المستخدم مفلتراً
    هو ما يريد جمعه، وجمع المصدر يعطي رقماً لا يطابق ما أمامه.
    """
    foot = set()
    for r in range(table.rowCount()):
        it = table.item(r, 0)
        if it is not None and it.data(TOTAL_ROLE):
            foot.add(r)
    out = {}
    for c in cols:
        s = 0.0
        for r in range(table.rowCount()):
            if r in foot:
                continue
            it = table.item(r, c)
            n = as_number(it.text() if it is not None else "")
            if n is not None:
                s += n
        out[c] = round(s, 3)
    return out


# ══════════════════════════════════════════════════════════════════
#  التصدير
# ══════════════════════════════════════════════════════════════════

def rows_of(table, include_header=True):
    """محتوى الجدول كما يُرى — مصفوفة نصوص جاهزة للتصدير."""
    out = []
    if include_header:
        out.append([table.horizontalHeaderItem(c).text()
                    if table.horizontalHeaderItem(c) else f"عمود {c + 1}"
                    for c in range(table.columnCount())])
    for r in range(table.rowCount()):
        if table.isRowHidden(r):
            continue
        out.append([(table.item(r, c).text() if table.item(r, c) else "")
                    for c in range(table.columnCount())])
    return out


def export_csv(parent, table, suggested="كشف"):
    """يحفظ الجدول ملفاً يفتحه Excel مباشرةً.

    **الترميز `utf-8-sig`**: Excel على ويندوز يقرأ CSV بترميز النظام
    ما لم يجد علامة الترتيب (BOM) في أوله، فتظهر العربية حروفاً
    مشوّهة. البايتات الثلاثة هذه هي الفرق بين ملفٍ يُسلَّم وملفٍ
    يُعاد.
    """
    try:
        if table.rowCount() == 0:
            info(parent, "لا توجد بيانات للتصدير.", "تصدير")
            return None
        stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            parent, "حفظ الكشف", f"{suggested}_{stamp}.csv",
            "ملف Excel/CSV (*.csv)")
        if not path:
            return None
        if not path.lower().endswith(".csv"):
            path += ".csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            csv.writer(fh).writerows(rows_of(table))
        info(parent, f"حُفظ الكشف:\n{path}", "تم التصدير")
        return path
    except Exception as e:
        err(parent, f"تعذّر التصدير: {e}")
        return None


def copy_clipboard(table):
    """ينسخ الجدول للحافظة مفصولاً بجدولة — يُلصق في Excel مباشرةً."""
    try:
        text = "\n".join("\t".join(r) for r in rows_of(table))
        QtWidgets.QApplication.clipboard().setText(text)
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
#  حفظ عروض الأعمدة
# ══════════════════════════════════════════════════════════════════

PREF_PREFIX = "cols_"


def _weights_from(table):
    """نِسَب عروض الأعمدة الحالية — لا بكسلاتها.

    البكسل يتبع الشاشة: عرضٌ مناسب على 27 بوصة يقصّ العمود على 13.
    النسبة تصلح للاثنتين، ومُحجِّم الأعمدة يعمل بها أصلاً.
    """
    n = table.columnCount()
    if n <= 0:
        return []
    ws = [max(1, table.columnWidth(c)) for c in range(n)]
    total = float(sum(ws)) or 1.0
    return [round(w * 100.0 / total, 2) for w in ws]


def save_widths(table, key, username=None):
    """يحفظ نِسَب الأعمدة تحت مفتاح الشاشة."""
    ws = _weights_from(table)
    if not ws:
        return False
    return save_pref(PREF_PREFIX + key, ",".join(str(x) for x in ws),
                     username)


def load_widths(key, n=None):
    """يقرأ النِسَب المحفوظة — وقائمةً فارغة إن لم تُطابق عدد الأعمدة."""
    raw = load_pref(PREF_PREFIX + key, "")
    if not raw:
        return []
    try:
        ws = [float(x) for x in str(raw).split(",") if x.strip()]
    except ValueError:
        return []
    if n is not None and len(ws) != int(n):
        return []           # تغيّرت أعمدة الشاشة — يُهمَل المحفوظ
    return ws


# ══════════════════════════════════════════════════════════════════
#  التركيب
# ══════════════════════════════════════════════════════════════════

def attach_menu(table, key=None):
    """قائمة الزر الأيمن: نسخٌ وتصدير — **آمنة على أي جدول**.

    لا تُعيد ترتيب صفٍّ ولا تمسّ محتوى، فتُركَّب على كل جداول النظام
    بلا استثناء: النسخ والتصدير حاجةٌ في شاشة الإدخال كما في التقرير.
    """
    try:
        # المفتاح يُقرأ عند الفتح لا عند التركيب: الجدول يُركَّب عليه
        # المنيو في `make_table` بلا مفتاح، ثم تسمّيه شاشته بعد قليل.
        if key:
            table.setProperty("_tt_key", key)
        if table.property("_tt_menu"):
            return False
        table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)

        def _menu(pos):
            key = table.property("_tt_key")
            m = QtWidgets.QMenu(table)
            a_copy = m.addAction("📋 نسخ الجدول (يُلصق في Excel)")
            a_csv = m.addAction("⬇ تصدير إلى Excel/CSV…")
            a_reset = None
            if key:
                m.addSeparator()
                a_reset = m.addAction("↺ إعادة عرض الأعمدة للافتراضي")
            act = m.exec_(table.viewport().mapToGlobal(pos))
            if act is a_copy:
                copy_clipboard(table)
            elif act is a_csv:
                export_csv(table.window(), table, key or "كشف")
            elif a_reset is not None and act is a_reset:
                reset_widths(table, key)

        table.customContextMenuRequested.connect(_menu)
        table.setProperty("_tt_menu", True)
        return True
    except Exception:
        return False


def attach_sorter(table):
    """الفرز بالنقر — **لشاشات العرض وحدها**.

    لماذا ليس لكل جدول: شاشات الإدخال تربط رقم الصف بترتيب عنصرٍ في
    قائمةٍ بالذاكرة (`items[currentRow()]`)، فإعادة ترتيب الصفوف
    تجعل «احذف المحدد» يحذف غير المحدد. الفرز يُطلب صراحةً حيث
    الجدول عرضٌ محضٌ لا مرآةَ قائمة.
    """
    try:
        if table.property("_tt_sorter"):
            return table.property("_tt_sorter")
        s = Sorter(table)
        table.setSortingEnabled(False)       # الفرز لنا لا لـQt
        table.setProperty("_tt_sorter", s)
        return s
    except Exception:
        return None


def attach_widths(table, key, username=None):
    """يستعيد عروض الأعمدة المحفوظة، ويحفظ ما يسحبه المستخدم.

    **كيف يتعايش مع مُحجِّم الأعمدة**: المُحجِّم يوزّع العرض المتاح
    بأوزان، وضبطُ بكسلات الأعمدة مباشرةً يضيع عند أول تغيير حجم. لذا
    السحب هنا يُترجَم **أوزاناً** تُسلَّم للمُحجِّم نفسه ويُحفظ بها —
    فالاختيار يصير جزءاً من التوزيع لا منافساً له، ويبقى صحيحاً على
    شاشةٍ أعرض أو أضيق.
    """
    if not key:
        return False
    try:
        hh = table.horizontalHeader()
        hh.setSectionsMovable(False)
        hh.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)

        def _commit():
            ws = _weights_from(table)
            if not ws:
                return
            table.setProperty("_user_weights", ws)
            save_pref(PREF_PREFIX + key, ",".join(str(x) for x in ws),
                      username)

        timer = QtCore.QTimer(table)
        timer.setSingleShot(True)
        timer.setInterval(500)
        timer.timeout.connect(_commit)

        def _on_resized(*_):
            # التوزيع الآلي ليس اختياراً من المستخدم: المُحجِّم يرفع
            # `_busy` أثناء كتابته العروض، فيُتجاهل ما يُطلقه هو.
            f = table.property("_fitter")
            if f is not None and getattr(f, "_busy", False):
                return
            timer.start()

        hh.sectionResized.connect(_on_resized)
        table.setProperty("_tt_widths", timer)
        apply_saved_widths(table, key)
        return True
    except Exception:
        return False


def reset_widths(table, key, username=None):
    """يعيد الأعمدة لتوزيعها الافتراضي ويمحو المحفوظ."""
    try:
        table.setProperty("_user_weights", None)
        save_pref(PREF_PREFIX + key, "", username)
        from ui.widgets.table_fit import fit_columns
        f = table.property("_fitter")
        if f is not None:
            f.refit()
        else:
            fit_columns(table)
        return True
    except Exception:
        return False


def enhance(table, key=None, username=None, sortable=True):
    """يركّب ما تحتاجه شاشة عرضٍ كاملة: فرز · قائمة · حفظ العروض.

    آمنة على أي جدول: كل جزء مستقل، وفشل أحدها لا يمنع الباقي ولا
    يُعطّل الشاشة. وتكرار ندائها لا يُركّب شيئاً مرتين.
    """
    bundle = {"key": key, "sorter": None}
    if sortable:
        bundle["sorter"] = attach_sorter(table)
    attach_menu(table, key)
    attach_widths(table, key, username)
    return bundle


def apply_saved_widths(table, key):
    """يطبّق النِسَب المحفوظة عبر مُحجِّم الأعمدة نفسه.

    لا نضبط البكسلات مباشرةً: المُحجِّم سيعيد توزيعها عند أول تغيير
    حجم فيضيع ما استُعيد. تمريرها إليه أوزاناً يجعل الاختيار جزءاً من
    التوزيع لا منافساً له.
    """
    try:
        ws = load_widths(key, table.columnCount())
        if not ws:
            return False
        from ui.widgets.table_fit import fit_columns
        table.setProperty("_fitting", True)
        try:
            fit_columns(table, ws)
        finally:
            table.setProperty("_fitting", False)
        return True
    except Exception:
        return False


def export_button(table, key="كشف", parent=None):
    """زر تصدير جاهز — تضعه الشاشة في شريط أدواتها."""
    b = QtWidgets.QPushButton("⬇ تصدير Excel")
    b.setObjectName("ghost")
    b.setToolTip("يحفظ الجدول المعروض ملفاً يفتحه Excel مباشرةً")
    b.clicked.connect(
        lambda: export_csv(parent or table.window(), table, key))
    return b
