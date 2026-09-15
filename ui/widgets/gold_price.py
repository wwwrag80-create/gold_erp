# -*- coding: utf-8 -*-
"""شريط سعر الأونصة العالمية الحي.

يجلب سعر أونصة الذهب لحظياً من الإنترنت ويحدّثه تلقائياً، ويعرض معه
سعر الجرام لعيار 24 و21 و18 محسوباً من الأونصة. يعمل في خيط مستقل فلا
يُجمّد الواجهة، ويعرض آخر سعر معروف إن انقطع الاتصال.
"""
import json
import urllib.request

from PyQt5 import QtCore, QtWidgets

OUNCE_GRAMS = 31.1034768          # الأونصة الترويّة بالجرام
REFRESH_MS = 300_000              # التحديث كل 5 دقائق
# دقيقة واحدة كانت تُنشئ 60 طلب شبكة في الساعة بلا داعٍ —
# سعر الذهب لا يتغيّر بما يستدعي ذلك، والتخفيف يريح النظام.

# معادلة عيار 18 المعتمدة: (سعر الذهب العالمي × 121) ÷ 1333.33
K18_FACTOR = 121.0
K18_DIVISOR = 1333.33

# مصادر مجانية بلا مفتاح — تُجرَّب بالترتيب حتى ينجح أحدها
SOURCES = [
    ("https://api.gold-api.com/price/XAU", ("price",)),
    ("https://api.metalpriceapi.com/v1/latest?base=XAU&currencies=USD",
     ("rates", "USD")),
    ("https://data-asg.goldprice.org/dbXRates/USD", ("items", 0, "xauPrice")),
]


def _dig(data, path):
    cur = data
    for k in path:
        cur = cur[k] if not isinstance(k, int) else cur[k]
    return float(cur)


def fetch_ounce_usd(timeout=6):
    """يجلب سعر الأونصة بالدولار من أول مصدر يستجيب."""
    last = None
    for url, path in SOURCES:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            val = _dig(data, path)
            if val and val > 0:
                return round(val, 2)
        except Exception as e:      # نجرّب المصدر التالي
            last = e
    raise RuntimeError(f"تعذّر جلب سعر الأونصة: {last}")


class _Fetcher(QtCore.QThread):
    """خيط مستقل لجلب السعر بلا تجميد الواجهة."""
    done = QtCore.pyqtSignal(float)
    failed = QtCore.pyqtSignal(str)

    def run(self):
        try:
            self.done.emit(fetch_ounce_usd())
        except Exception as e:
            self.failed.emit(str(e))


class GoldPriceBar(QtWidgets.QFrame):
    """شريط بارز يعرض سعر الأونصة وأسعار الجرام لكل عيار."""

    def __init__(self, usd_to_sar=3.75):
        super().__init__()
        self.usd_to_sar = usd_to_sar
        self.setObjectName("goldBar")
        self._thread = None
        self._last = None

        self.title = QtWidgets.QLabel("سعر الذهب العالمي")
        self.title.setObjectName("goldBarTitle")
        self.title.setAlignment(QtCore.Qt.AlignCenter)

        self.ounce = QtWidgets.QLabel("— جارِ التحميل —")
        self.ounce.setObjectName("goldBarValue")
        self.ounce.setAlignment(QtCore.Qt.AlignCenter)

        # حقل منفصل وواضح لكل عيار
        self.karat_labels = {}
        self.grid = QtWidgets.QGridLayout()
        # تباعد أوسع قليلاً: البطاقات صارت مؤطّرة فتحتاج متنفّساً
        self.grid.setSpacing(5)
        for i, k in enumerate((24, 22, 21, 18)):
            cap = QtWidgets.QLabel(f"عيار {k}")
            cap.setObjectName("goldBarSub")
            cap.setAlignment(QtCore.Qt.AlignCenter)
            val = QtWidgets.QLabel("—")
            val.setObjectName("goldKarat")
            val.setAlignment(QtCore.Qt.AlignCenter)
            self.karat_labels[k] = val
            self.grid.addWidget(cap, i // 2 * 2, i % 2)
            self.grid.addWidget(val, i // 2 * 2 + 1, i % 2)

        self.stamp = QtWidgets.QLabel("")
        self.stamp.setObjectName("goldBarStamp")
        self.stamp.setAlignment(QtCore.Qt.AlignCenter)

        btn = QtWidgets.QPushButton("↻ تحديث الآن")
        btn.setObjectName("ghost")
        btn.clicked.connect(self.refresh)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(3)
        lay.addWidget(self.title)
        lay.addWidget(self.ounce)
        lay.addLayout(self.grid)
        lay.addWidget(self.stamp)
        lay.addWidget(btn)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)
        QtCore.QTimer.singleShot(600, self.refresh)

    def refresh(self):
        """يجلب السعر في خيط مستقل — بخيط واحد يُنظَّف بعد انتهائه.

        **الخلل السابق**: كان يُنشأ خيط جديد كل دقيقة بلا حذف، فتتراكم
        عشرات الخيوط خلال ساعة ويثقل النظام حتى يتجمّد — وهو سبب
        «النظام يعلّق بعد عشر دقائق».

        الآن: خيط واحد فقط في كل لحظة، ويُحذف بـ`deleteLater` عند
        انتهائه فلا يبقى منه أثر.
        """
        old = self._thread
        if old is not None:
            try:
                if old.isRunning():
                    return          # جلب جارٍ — لا نُنشئ ثانياً
            except RuntimeError:
                pass                # كائن محذوف: نتابع بخيط جديد
        th = _Fetcher()
        th.done.connect(self._ok)
        th.failed.connect(self._err)
        # التنظيف الذاتي: الخيط يُحذف بمجرد انتهائه
        th.finished.connect(th.deleteLater)
        th.finished.connect(self._thread_done)
        self._thread = th
        th.start()

    def _thread_done(self):
        """يُفرِغ المرجع بعد انتهاء الخيط فلا يبقى معلّقاً."""
        self._thread = None

    def closeEvent(self, e):
        """يوقف المؤقّت والخيط عند إغلاق الشريط."""
        try:
            self.timer.stop()
            th = self._thread
            if th is not None and th.isRunning():
                th.quit()
                th.wait(1500)
        except Exception:
            pass
        super().closeEvent(e)

    def _ok(self, usd):
        self._last = usd
        sar = usd * self.usd_to_sar
        g24 = sar / OUNCE_GRAMS
        self.ounce.setText(f"{usd:,.2f} $   ·   {sar:,.2f} ر.س")
        prices = {
            24: g24,
            22: g24 * 22 / 24,
            21: g24 * 21 / 24,
            # معادلة عيار 18 الخاصة المعتمدة:
            # (سعر الذهب العالمي × 121) ÷ 1333.33
            18: usd * K18_FACTOR / K18_DIVISOR,
        }
        for k, lbl in self.karat_labels.items():
            lbl.setText(f"{prices[k]:,.2f} ر.س")
        self.stamp.setText(
            "آخر تحديث: "
            + QtCore.QTime.currentTime().toString("HH:mm:ss"))

    def _err(self, msg):
        if self._last is None:
            self.ounce.setText("تعذّر الاتصال")
        self.stamp.setText("محاولة الاتصال…")
