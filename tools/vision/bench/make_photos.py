# -*- coding: utf-8 -*-
"""يحفظ لقطات «الجوال» (ضجيج · ضغط · ميلان لوني) ملفاتٍ JPEG للتجربة في المتصفح.

    python make_photos.py <مجلد-المجموعة>

الناتج: <المجموعة>/photos/<الطقم>_p<رقم>.jpg  وفهرسها photos.json
— بالدالة نفسها التي يقيّم بها evaluate.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate import phoneify  # noqa: E402

B = Path(sys.argv[1])
meta = json.loads((B / "meta.json").read_text(encoding="utf-8"))
out = B / "photos"
out.mkdir(exist_ok=True)
rows = []
for m in meta:
    for k, s in enumerate(m["shots"]):
        seed = hash((m["id"], k)) & 0xFFFF
        im = phoneify(B / "raw" / s["file"], seed)
        f = out / f"{m['id']}_p{k}.jpg"
        im.save(f, "JPEG", quality=90)
        rows.append({"file": f.name, "id": m["id"], "kind": s["kind"]})
(B / "photos.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print(len(rows), "لقطة")
