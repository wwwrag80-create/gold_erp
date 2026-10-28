# -*- coding: utf-8 -*-
"""حارس المسوّدة — ما أُدخل ولم يُرحَّل يُحفظ **وهو يُكتب** (5.0).

**الحادثة**: أسطر فاتورة مبيعات تُضاف ولم تُرحَّل، فانقطعت الكهرباء
وانطفأ الجهاز. ولمّا عاد البرنامج كانت الفاتورة فارغة. فالمسوّدة
(`services/drafts.py`) كانت تُحفظ عند **مغادرة** الشاشة وحدها — ومنذ
4.97 تبقى الشاشات حيّةً في الذاكرة فلا تُغادَر أصلاً حتى يُغلق
البرنامج. وانقطاع الكهرباء لا يُغلق شيئاً.

**الحارس**: يقرأ `draft_state()` من الشاشة كل لحظات (`INTERVAL`)،
فإن تغيّر عمّا حُفظ آخر مرة كتبه في القاعدة. أقصى ما يضيع بانقطاعٍ
مفاجئ ثانيتان ونصف من الكتابة لا الفاتورة كلها. والقاعدة بوضع
`synchronous=FULL` فما كُتب ثبت على القرص قبل أن يعود الأمر.

* لا كتابة إن لم يتغيّر شيء — الشاشة الهادئة لا تمسّ القرص.
* لا ينضمّ إلى معاملةٍ مفتوحة في الشاشة (نافذة تأكيدٍ وسط ترحيل):
  يؤجَّل إلى الدورة التالية.
* يُحفظ كذلك عند إغلاق البرنامج وعند إيقاف ويندوز (`commitDataRequest`).
* وضع التعديل لا مسوّدة له — `draft_state()` تعيد None فيه.
"""
import json
import weakref

from PyQt5 import QtCore, QtWidgets

from services import drafts

INTERVAL = 2500          # مللي ثانية بين فحصٍ وآخر
_KEEPERS = weakref.WeakSet()
_HOOKED = [False]


def _dumps(state):
    if not state:
        return ""
    try:
        return json.dumps(state, ensure_ascii=False, sort_keys=True,
                          default=str)
    except Exception:
        return None          # حالةٌ لا تُسلسَل: لا تُحفظ ولا تمحو شيئاً


def flush_all():
    """يحفظ مسوّدات كل الشاشات الحيّة الآن — قبل الإغلاق أو الإيقاف."""
    for k in list(_KEEPERS):
        try:
            k.tick(force=True)
        except Exception:
            pass


def _hook_app():
    if _HOOKED[0]:
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    _HOOKED[0] = True
    try:
        app.aboutToQuit.connect(flush_all)
        app.commitDataRequest.connect(lambda *_: flush_all())
    except Exception:
        pass


class DraftKeeper(QtCore.QObject):
    """يُنشأ مرةً لكل شاشة بعد محاولة استعادة مسوّدتها."""

    def __init__(self, screen, key, username, interval=INTERVAL):
        super().__init__(screen)
        self.screen = screen
        self.key = key
        self.user = username or ""
        # ما في الشاشة الآن هو المحفوظ (مسوّدةٌ استُعيدت أو لا شيء) —
        # فلا تُعاد كتابته في أول دورة
        try:
            self.saved = _dumps(screen.draft_state())
        except Exception:
            self.saved = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(int(interval))
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        _KEEPERS.add(self)
        _hook_app()

    def tick(self, force=False):
        try:
            from database.database import in_transaction
            if in_transaction():
                return False      # الشاشة وسط معاملة — الدورة التالية
        except Exception:
            pass
        try:
            state = self.screen.draft_state()
        except Exception:
            return False
        payload = _dumps(state)
        if payload is None or (payload == self.saved and not force):
            return False
        if payload == self.saved:
            return True
        if drafts.save(self.key, self.user, state):
            self.saved = payload
            return True
        return False

    def cleared(self):
        """المسوّدة مُحيت (رُحّل المستند) — لا داعي لكتابة الفراغ ثانيةً."""
        self.saved = ""


def keep(screen, key, username):
    """يُركّب الحارس على الشاشة مرةً واحدة ويعيده."""
    k = getattr(screen, "_draft_keeper", None)
    if k is None:
        k = DraftKeeper(screen, key, username)
        screen._draft_keeper = k
    return k
