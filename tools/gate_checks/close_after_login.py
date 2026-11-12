"""دخولٌ ناجح حقيقي: البوابة تُغلق بعد ظهور النظام — لا تبقى سوداء خلفه."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GOLD_ERP_REDUCE_MOTION"] = sys.argv[1] if len(sys.argv) > 1 else "0"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from PyQt5 import QtCore, QtWidgets
from ui.gate_window import GateWindow
from services import login_flow
import main
app = QtWidgets.QApplication(sys.argv)
gate = GateWindow()
gate.prepare([("x", lambda: None)])
class FakeWin(QtWidgets.QMainWindow):
    def __init__(self, session):
        super().__init__(); self.setWindowTitle("system")
    def play_entrance(self): pass
    def toast(self, *a, **k): pass
holder = main.wire_gate(app, gate, FakeWin)
login_flow.sign_in = lambda u, p, on_progress=None, on_restored=None: {"username": "admin", "full_name": "المدير العام", "id": 1, "role": "admin"}
gate.setGeometry(0, 0, 1280, 800); gate.show()
def go():
    gate._ensure_card(); gate.card.show()
    gate._ready = True; gate.btn.setEnabled(True)
    gate.username.setText("admin"); gate.password.setText("x")
    gate.try_login()
def end():
    w = holder.get("win")
    print("motion", sys.argv[1:], "| system shown:", bool(w and w.isVisible()), "| gate visible:", gate.isVisible(), flush=True)
    app.quit()
QtCore.QTimer.singleShot(800, go)
QtCore.QTimer.singleShot(7000, end)
app.exec_()
