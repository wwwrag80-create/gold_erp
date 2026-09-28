# -*- coding: utf-8 -*-
"""شاشاتٌ بلا فقراتِ شرح — المساحة للجدول.

**لماذا**: كل شاشةٍ تقريباً كانت تحمل فقرةً أو اثنتين تشرح ما تفعله
(«قراءة محضة: لا يُنشأ قيد…»، «اضغط أي لوحة لعرض…»). يقرؤها المستخدم
مرةً في أول يوم، ثم تبقى تأكل من الشاشة سطرين أو ثلاثة كل يوم —
والجدول تحتها يقصر بقدرها.

**الآن**: تُطوى هذه الفقرات تلقائياً في كل شاشة، فيتمدّد الجدول مكانها.
ولا يضيع الشرح: زرّ «ⓘ» صغير في الشريط العلوي بجوار اسم الشاشة يعرضه
عند الحاجة، ومن «عرض ← إظهار الملاحظات التوضيحية» تعود كما كانت.

**ما يُطوى** (يُعرَف بلا تعديل أي شاشة):
  · ملصقٌ بنمط الملاحظة (`cardSub`) نصُّه جملةٌ طويلة — شرحٌ لا قيمة.
  · عنوان الشاشة الكبير (`title`) أعلاها: اسمها ظاهرٌ في الشريط العلوي
    أصلاً، فكان يتكرّر سطراً ثانياً فوق كل شاشة. ويبقى نصّه الكامل
    رأسَ بطاقة «ⓘ».
  · داخل شاشةٍ من شاشات النافذة الرئيسية — لا في نافذة حوار (الحوار
    صغيرٌ وقراره يحتاج شرحه).

**ما لا يُطوى أبداً**:
  · سطر البطاقة الفرعي (داخل بطاقة أرقام) — جزءٌ من الرقم.
  · عناوين الخانات القصيرة («رقم التشغيل»، «الذهب»…).
  · الملصق الحيّ الذي تكتب فيه الشاشة حالتها (`live`): حالة الدورة،
    آخر صيانة، الأجرة المتفق عليها… — هذه معلومةٌ لا شرح.
  · التنبيهات (`warn`/`ok`) وشارة وضع التعديل.
"""
from PyQt5 import QtCore, QtWidgets

PREF = "ui_show_notes"
NOTE_NAMES = {"cardSub"}
TITLE_NAMES = {"title"}
MIN_LEN = 40          # أقصر من هذا عنوانُ خانةٍ أو قيمة، لا شرح
LIVE = "live"         # خاصيةٌ تضعها الشاشة على ملصقٍ تكتب فيه حالتها
NOTE = "note"         # وعكسها: ملصقٌ شرحٌ دائماً ولو كان فارغاً لحظة ظهوره
SCREEN_HOST = "screenHost"      # اسم مكدّس الشاشات في النافذة الرئيسية
_HIDDEN = "_note_folded"
# إطاراتٌ ملصقاتها جزءٌ من رقم (بطاقات · لوحات) — لا تُمسّ
_KEEP_IN = {"card", "cardSum", "kpi", "kpiAlert", "kpiGood", "tile",
            "statPanel", "goldBar", "ratioBar"}

_show = None


def showing():
    """هل اختار المستخدم إظهار الملاحظات؟ (الافتراضي: مطويّة)."""
    global _show
    if _show is None:
        try:
            from ui.widgets.common import load_pref
            _show = str(load_pref(PREF, "0")).strip() == "1"
        except Exception:
            _show = False
    return _show


def set_showing(on, username=None):
    global _show
    from ui.widgets.common import save_pref
    save_pref(PREF, "1" if on else "0", username)
    _show = bool(on)
    for w in QtWidgets.QApplication.allWidgets():
        if on and w.property(_HIDDEN):
            w.setProperty(_HIDDEN, False)
            w.setVisible(True)
        elif not on and isinstance(w, QtWidgets.QLabel) and foldable(w) \
                and w.isVisible():
            fold(w)


def in_screen(w):
    """هل الملصق داخل شاشةٍ من شاشات النافذة الرئيسية (لا حوار)؟"""
    p = w.parentWidget()
    while p is not None:
        if p.objectName() == SCREEN_HOST:
            return True
        if p.isWindow():
            return False
        p = p.parentWidget()
    return False


def _inside_card(w):
    p = w.parentWidget()
    while p is not None and not p.isWindow():
        if p.objectName() == SCREEN_HOST:
            return False
        if p.objectName() in _KEEP_IN:
            return True
        p = p.parentWidget()
    return False


def is_note(lbl):
    """فقرة شرحٍ تُطوى؟ (بلا نظرٍ للتفضيل)."""
    try:
        if not isinstance(lbl, QtWidgets.QLabel):
            return False
        if lbl.objectName() not in NOTE_NAMES or lbl.property(LIVE):
            return False
        # `note`: شرحٌ تكتبه الشاشة لاحقاً (فارغٌ لحظة الظهور) — يُطوى
        if not lbl.property(NOTE) and len((lbl.text() or "").strip()) < MIN_LEN:
            return False
        return in_screen(lbl) and not _inside_card(lbl)
    except RuntimeError:          # ملصقٌ حُذف كائنه في C++
        return False


def is_title(lbl):
    """عنوان شاشةٍ يكرّر اسمها الظاهر في الشريط العلوي؟"""
    try:
        return (isinstance(lbl, QtWidgets.QLabel)
                and lbl.objectName() in TITLE_NAMES
                and not lbl.property(LIVE) and in_screen(lbl))
    except RuntimeError:
        return False


def foldable(lbl):
    return is_note(lbl) or is_title(lbl)


def title_in(root):
    """عنوان الشاشة المطويّ (أوّل عنوان) — أو نصٌّ فارغ."""
    try:
        for lbl in root.findChildren(QtWidgets.QLabel):
            if lbl.objectName() in TITLE_NAMES and (lbl.text() or "").strip():
                return " ".join(lbl.text().split())
    except (RuntimeError, AttributeError):
        pass
    return ""


def fold(lbl):
    lbl.setProperty(_HIDDEN, True)
    lbl.setVisible(False)


def notes_in(root):
    """نصوص الشرح في شاشةٍ — ظاهرةً أو مطويّة — لزرّ «ⓘ»."""
    out = []
    if root is None:
        return out
    try:
        labels = root.findChildren(QtWidgets.QLabel)
    except RuntimeError:
        return out
    for lbl in labels:
        if lbl.objectName() in TITLE_NAMES:
            continue
        if lbl.property(_HIDDEN) or is_note(lbl):
            t = " ".join((lbl.text() or "").split())
            if t and t not in out:
                out.append(t)
    return out


class _Folder(QtCore.QObject):
    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.Show and isinstance(obj,
                                                          QtWidgets.QLabel):
            try:
                if not showing() and foldable(obj):
                    fold(obj)
            except Exception:
                pass
        return False


_installed = None


def install(app):
    """يركّب المرشّح على التطبيق — مرةً واحدة."""
    global _installed
    if _installed is None:
        _installed = _Folder(app)
        app.installEventFilter(_installed)
    return _installed
