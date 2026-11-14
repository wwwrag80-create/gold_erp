import os, sys, pathlib, tempfile, time
os.environ["QT_QPA_PLATFORM"]="offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
tmp=tempfile.mkdtemp(); os.environ["GOLD_ERP_DATA_DIR"]=tmp
from PyQt5 import QtWidgets, QtCore
app=QtWidgets.QApplication([])
import config; config.DB_PATH=pathlib.Path(tmp)/"t.db"
import main
for label, fn in main.prepare_steps()[:-1]: fn()
from ui.main_window import MainWindow
w=MainWindow({"id":1,"username":"admin","full_name":"م","role":"admin","role_local":"accountant"})
w.resize(1500,900); w.show()
def pump(n=30):
    for _ in range(n): app.processEvents(); time.sleep(0.02)
pump()
mode = sys.argv[1]
d = w.dashboard_screen
if mode == "renamed":
    w._items[d].setText(0, "الرئيسية — لوحتي")
elif mode == "missing":
    w._items.pop(d, None)
toasts=[]; w.toast=lambda t, ms=0: toasts.append(t)
w.open_by_title("سندات قبض/صرف"); pump()
for i in range(w._tools_lay.count()):
    b=w._tools_lay.itemAt(i).widget()
    if "صناديق" in b.text(): b.click()
pump(40)
cur = w.screens[w._current_row]
print(mode, "| on dashboard:", cur is d, "| panel:", d.real.panels[d.real.current].get("key"), "| toasts:", toasts)
