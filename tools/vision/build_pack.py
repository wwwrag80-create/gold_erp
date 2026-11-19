# -*- coding: utf-8 -*-
"""يبني «حزمة أدوات البحث بالصورة» التي ينزّلها جهاز المصنع مرةً واحدة.

    python build_pack.py <نموذج.onnx> <مجلد onnxruntime-web/dist> <ناتج.zip>
           --id <معرّف> --input 224 --skip 5 --pool cls+mean
           [--license ملف]… [--fp16-weights]

* `--fp16-weights`: أوزان النموذج تُخزَّن بنصف الحجم (float16) ويُضاف قبل كلٍّ
  منها تحويلٌ إلى float32 — يطويه المحرّك عند التحميل، فالحساب كما هو
  (float32) والتنزيل نصف حجمه.
* ملفات المحرّك الكبيرة تُضاف مضغوطةً أيضاً (.gz) فيرسلها الخادم مضغوطة.
* يطبع البصمة (SHA-256) والحجم — يُثبَّتان في `services/vision_search.py`.

أداة تطوير (تحتاج حزمة onnx) لا يحتاجها البرنامج.
"""
import argparse
import gzip
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

ORT_FILES = ("ort.wasm.min.js", "ort-wasm-simd-threaded.wasm",
             "ort-wasm-simd-threaded.mjs")


def fp16_weights(src, dst, min_size=1024):
    import numpy as np
    import onnx
    from onnx import helper, numpy_helper, TensorProto
    m = onnx.load(str(src))                 # يقرأ ملف الأوزان الخارجي إن وُجد
    g = m.graph
    casts = []
    keep = []
    for init in g.initializer:
        if init.data_type == TensorProto.FLOAT:
            a = numpy_helper.to_array(init)
            if a.size >= min_size:
                h = numpy_helper.from_array(a.astype(np.float16), init.name + "__f16")
                keep.append(h)
                casts.append(helper.make_node("Cast", [h.name], [init.name],
                                              to=TensorProto.FLOAT,
                                              name=init.name + "__cast"))
                continue
        keep.append(init)
    del g.initializer[:]
    g.initializer.extend(keep)
    nodes = list(g.node)
    del g.node[:]
    g.node.extend(casts + nodes)
    onnx.save(m, str(dst))
    return len(casts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("ortdist")
    ap.add_argument("out")
    ap.add_argument("--id", required=True)
    ap.add_argument("--input", type=int, default=224)
    ap.add_argument("--skip", type=int, default=1)
    ap.add_argument("--pool", default="cls+mean")
    ap.add_argument("--output", default="last_hidden_state")
    ap.add_argument("--input-name", default="pixel_values")
    ap.add_argument("--mean", default="0.485,0.456,0.406")
    ap.add_argument("--std", default="0.229,0.224,0.225")
    ap.add_argument("--views", default='{"work":384,"pieces":5,"windows":true}')
    ap.add_argument("--query", default='{"crops":[0.8,0.62],"flip":true}')
    ap.add_argument("--agg", default="meanmax")
    ap.add_argument("--thr", default='{"hi":0.7,"mid":0.55,"gap":0.02}')
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--license", action="append", default=[])
    ap.add_argument("--fp16-weights", action="store_true")
    a = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="vpack_"))
    model = tmp / "model.onnx"
    if a.fp16_weights:
        n = fp16_weights(a.model, model)
        print(f"أوزان float16: {n} مصفوفة")
    else:
        import onnx
        onnx.save(onnx.load(a.model), str(model))
    for f in ORT_FILES:
        shutil.copy(Path(a.ortdist) / f, tmp / f)
        with open(tmp / f, "rb") as s, gzip.open(tmp / (f + ".gz"), "wb", 9) as d:
            shutil.copyfileobj(s, d)
    lic = ["ONNX Runtime Web — MIT License — Copyright (c) Microsoft Corporation."]
    for p in a.license:
        lic.append("\n\n" + "=" * 70 + f"\n{Path(p).name}\n" + "=" * 70 + "\n"
                   + Path(p).read_text(encoding="utf-8"))
    (tmp / "LICENSES.txt").write_text("".join(lic), encoding="utf-8")
    man = {
        "id": a.id, "input": a.input, "input_name": a.input_name,
        "output": a.output, "skip": a.skip, "pool": a.pool,
        "mean": [float(x) for x in a.mean.split(",")],
        "std": [float(x) for x in a.std.split(",")],
        "views": json.loads(a.views), "query": json.loads(a.query),
        "agg": a.agg, "thr": json.loads(a.thr), "batch": a.batch,
        "size_bytes": model.stat().st_size,
        "files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                  for f in sorted(tmp.iterdir())},
    }
    (tmp / "manifest.json").write_text(json.dumps(man, indent=1),
                                       encoding="utf-8")
    out = Path(a.out)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        for f in sorted(tmp.iterdir()):
            z.write(f, f.name)
    sha = hashlib.sha256(out.read_bytes()).hexdigest()
    print(json.dumps({"file": out.name, "size": out.stat().st_size,
                      "sha256": sha, "dir": str(tmp)}, indent=1))


if __name__ == "__main__":
    main()
