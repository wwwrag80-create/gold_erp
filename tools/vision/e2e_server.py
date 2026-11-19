# -*- coding: utf-8 -*-
"""خادم تجربة «البحث بالصورة» من طرفٍ لطرف: البرنامج الحقيقي ورابطه.

    python3 tools/vision/e2e_server.py <مجلد-المجموعة> <مجلد-الحزمة> <ملف-الإعداد.json>

يبني قاعدةً مؤقتة: لكل طقمٍ في المجموعة موديلٌ باسمه (F00V0 …) بصورة
الكتالوج، وقطعتان منه (واحدةٌ بالخزنة وأخرى عند مندوب) — ثم يشغّل خادم
البرنامج والرابط مفعّلٌ، ويكتب العنوان في ملف الإعداد ويبقى يعمل.
"""
import datetime
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
BENCH, PACK, OUT = (pathlib.Path(a) for a in sys.argv[1:4])
T = tempfile.mkdtemp(prefix="vis_e2e_")
os.environ["GOLD_ERP_DATA_DIR"] = T
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# مجلّد حزمةٍ جاهز — أو ملف الحزمة الرسمي نفسه (.zip) يُثبَّت بمسار البرنامج
# الحقيقي (مطابقة البصمة المثبّتة فيه)
if PACK.suffix != ".zip":
    os.environ["JADEITE_VISION_PACK_DIR"] = str(PACK)
import config  # noqa: E402

config.DB_PATH = pathlib.Path(T) / "t.db"
import main  # noqa: E402

for _l, f in main.prepare_steps():
    f()
from database.database import db  # noqa: E402
from models import inventory, invoices, models_catalog as mc  # noqa: E402
from models.entities import add_entity  # noqa: E402
from services import models_web as mw, photo_server  # noqa: E402

meta = json.loads((BENCH / "meta.json").read_text(encoding="utf-8"))
ids = [m["id"] for m in meta]
D0 = datetime.date.today().isoformat()
with db() as c:
    rep = add_entity(c, "المندوب سالم", "customer", username="t")
    inventory.create_work_orders_batch(c, [
        {"wo_no": f"{1000 + 2 * i + j}", "model_no": m, "gold": 20 + i % 7,
         "small_stones": 0, "big_stones": 0, "wage_per_gram": 10}
        for i, m in enumerate(ids) for j in range(2)], D0, "t")
    W = {r[1]: r[0] for r in c.execute("SELECT id, work_order_no FROM work_orders")}
    invoices.create_sale(c, rep, [{"work_order_id": W[f"{1000 + 2 * i}"]}
                                  for i in range(len(ids))], D0, "t", apply_vat=False)
    tok = mw.ensure_token(c)
    mw.set_enabled(c, True)
    mw.set_mode(c, "lan")
for i in ids:
    shutil.copy(BENCH / "catalog" / f"{i}.png", mc.images_dir() / f"{i}.png")
if PACK.suffix == ".zip":
    import hashlib  # noqa: E402
    from services import vision_search as vs  # noqa: E402
    sha = hashlib.sha256(PACK.read_bytes()).hexdigest()
    assert sha == vs.PACK_SHA, "الحزمة ليست الرسمية المثبّتة في البرنامج"
    vs.install_zip(PACK, sha)
    assert vs.pack_ready()
    print("official pack installed", vs.manifest().get("id"), flush=True)
mw.register()
srv = photo_server._bind(0)
import threading  # noqa: E402
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
url = f"http://127.0.0.1:{port}/{mw.PREFIX}/{tok}"
OUT.write_text(json.dumps({"url": url, "data": T}), encoding="utf-8")
print("ready", url, flush=True)
while True:
    time.sleep(3600)
