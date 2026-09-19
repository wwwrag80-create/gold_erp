# -*- coding: utf-8 -*-
"""صحة النظام — صفحةٌ واحدة يُطمأنّ بها قبل تسليم الدفتر.

**لماذا شاشة مستقلة**: فحوص السلامة كانت محجوبة خلف حساب الإدارة
العليا، والمحاسب هو من يحتاجها: قبل إقفال شهر، وقبل تسليم كشفٍ
لمراجع، وحين يشكو من بطءٍ لا يعرف سببه.

تجمع أربعة أسئلة لا يجيبها غيرها:

1. **هل الدفتر متوازن؟** قيدٌ غير متوازن خللٌ صامت لا يظهر في كشف.
2. **هل هناك يتامى؟** فاتورةٌ بلا قيد أو قيدٌ بلا مستند.
3. **هل إجماليات الفواتير تطابق بنودها؟**
4. **أين تجمّد النظام؟** مواضع التجمّد التي رصدها الحارس بملفّها
   وسطرها — فالشكوى «شاشة سوداء» تصير سطراً يُقرأ ويُعالَج.

**قراءة محضة**: لا تُصلح ولا تكتب شيئاً. تكشف فتُعالَج الأسباب في
مواضعها.
"""
from PyQt5 import QtWidgets

from database.database import db
from services import health
from ui.widgets.common import big_label, err, fill, info, make_table, \
    title_label
from ui.widgets.table_tools import enhance

COLS = ["الحالة", "الفحص", "النتيجة"]


class DiagnosticsScreen(QtWidgets.QWidget):
    def __init__(self, user):
        super().__init__()
        self.user = user

        self.state = big_label("اضغط «فحص الآن».")
        btn = QtWidgets.QPushButton("🩺 فحص الآن")
        btn.clicked.connect(self.run_check)
        btn_log = QtWidgets.QPushButton("📄 آخر الأخطاء والبطء")
        btn_log.setObjectName("ghost")
        btn_log.clicked.connect(self.show_log)
        btn_clear = QtWidgets.QPushButton("🧹 مسح السجل")
        btn_clear.setObjectName("ghost")
        btn_clear.setToolTip("يمسح ملف الأخطاء والبطء — لا يمسّ أي بيانات")
        btn_clear.clicked.connect(self.clear_log)

        self.table = make_table()
        enhance(self.table, key="diagnostics")
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(btn)
        top.addWidget(btn_log)
        top.addWidget(btn_clear)
        top.addStretch(1)
        top.addWidget(self.state)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(title_label("صحة النظام — توازن الدفتر وسلامته"))
        intro = QtWidgets.QLabel(
            "قراءة محضة: لا تُصلح شيئاً ولا تكتب رقماً — تكشف الخلل "
            "ليُعالَج في موضعه. شغّلها قبل إقفال الشهر وقبل تسليم أي "
            "كشف لمراجع.")
        intro.setObjectName("cardSub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addLayout(top)
        lay.addWidget(self.table, 1)
        note = QtWidgets.QLabel(
            "«مواضع التجمّد» يرصدها حارسٌ يعمل مع النظام: متى توقّفت "
            "الواجهة عن الاستجابة ثوانيَ سجّل الملف والسطر والدالة — "
            "فالشكوى تصير دليلاً بدل تخمين.")
        note.setObjectName("cardSub")
        note.setWordWrap(True)
        lay.addWidget(note)

    def run_check(self):
        try:
            with db(readonly=True) as conn:
                h = health.full_health(conn)
        except Exception as e:
            err(self, e)
            return
        rows = []

        def add(ok, name, detail):
            rows.append(("✔ سليم" if ok else "⛔ خلل", name, detail))

        add(not h["unbalanced"], "توازن القيود المزدوجة",
            "كل القيود متوازنة في البعدين" if not h["unbalanced"]
            else f"{len(h['unbalanced'])} قيداً غير متوازن — "
                 f"الأرقام: {', '.join(str(x) for x in h['unbalanced'][:8])}")
        add(not h["orphans"], "السجلات اليتيمة",
            "لا سجل بلا مستنده" if not h["orphans"]
            else " · ".join(str(x) for x in h["orphans"][:5]))
        add(not h["integrity"], "سلامة ملف قاعدة البيانات",
            "الملف سليم" if not h["integrity"]
            else " · ".join(str(x) for x in h["integrity"][:5]))
        add(not h["invoice_totals"], "إجماليات الفواتير = مجموع بنودها",
            "متطابقة" if not h["invoice_totals"]
            else f"{len(h['invoice_totals'])} فاتورة إجماليها يخالف بنودها")

        # ══ الأرصدة المادية السالبة ══
        # بديل الحارس اللحظي الذي أُلغي: السالب لحظةَ البيع حالةٌ
        # واقعية تتكرّر، والتنبيه عليها يُتجاهَل. أما السالب الباقي
        # عند المراجعة فخللٌ حقيقي — توريدٌ لم يُسجَّل أو وزنٌ خرج
        # مرتين — فمكانه هنا: يُقرأ عند الحاجة ولا يقاطع عملاً.
        neg = h.get("negatives") or []
        if neg:
            from services import karat_view as _kv
            bits = []
            for r in neg[:5]:
                p = []
                if r["gold"]:
                    p.append(f"ذهب {_kv.g(r['gold']):,.3f}")
                if r["cash"]:
                    p.append(f"نقد {r['cash']:,.2f}")
                bits.append(f"{r['name']} ({' · '.join(p)})")
            rows.append(("⚠ يُراجَع", "أرصدة مادية سالبة",
                         " · ".join(bits)))
        else:
            add(True, "الأرصدة المادية (خزينة · مشغول · كسر · صندوق)",
                "لا رصيد سالب")

        # سلسلة بصمات القيود
        try:
            from models import integrity as _ig
            with db(readonly=True) as conn:
                st = _ig.status(conn)
            add(st["ok"], "سلسلة بصمات القيود",
                f"{st['sealed']:,} مختوم · {st['unsealed']:,} بلا بصمة"
                + ("" if st["ok"] else f" · {st['breaks']} موضع خلل"))
        except Exception:
            pass

        # مواضع التجمّد التي رُصدت في هذه الجلسة
        try:
            from services import ui_watchdog
            st2 = ui_watchdog.stalls()
            add(st2["count"] == 0, "تجمّد الواجهة (هذه الجلسة)",
                "لم يُرصد تجمّد" if not st2["count"]
                else f"{st2['count']} مرة — " + " · ".join(st2["places"][:3]))
        except Exception:
            pass

        add(h["recent_errors"] == 0, "أخطاء مسجّلة",
            "لا أخطاء" if not h["recent_errors"]
            else f"{h['recent_errors']} سطراً في السجل — افتح «آخر "
                 f"الأخطاء والبطء»")

        fill(self.table, COLS, rows)
        bad = [r for r in rows if r[0].startswith("⛔")]
        rev = [r for r in rows if r[0].startswith("⚠")]
        # السالب يُراجَع ولا يُعدّ خللاً: الدفتر قد يكون متوازناً
        # تماماً ورصيدُه سالب — وهي حالة تُصحَّح بتوريدٍ لا بقيد.
        if bad:
            self.state.setText(f"⛔ {len(bad)} خلل يحتاج مراجعة")
        elif rev:
            self.state.setText(f"✔ الدفتر سليم · {len(rev)} بندٌ يُراجَع")
        else:
            self.state.setText("✔ النظام سليم")

    def show_log(self):
        """آخر ما سُجّل من أخطاء وبطء — نصّاً كما هو."""
        try:
            lines = health.recent_errors(60)
        except Exception as e:
            err(self, e)
            return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("آخر الأخطاء والبطء")
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setText(f"آخر {len(lines)} سطراً من سجل النظام:")
        box.setDetailedText("\n".join(str(x) for x in lines)
                            or "السجل فارغ — لم يُسجَّل خطأ ولا بطء.")
        box.exec_()

    def clear_log(self):
        try:
            health.clear_errors()
            info(self, "مُسح سجل الأخطاء والبطء.\n\n"
                       "لم تُمسّ أي بيانات محاسبية.")
            self.run_check()
        except Exception as e:
            err(self, e)

    def refresh(self):
        self.run_check()
