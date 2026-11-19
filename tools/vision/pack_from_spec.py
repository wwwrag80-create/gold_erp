# -*- coding: utf-8 -*-
"""يبني الحزمة من مواصفتها `pack.json` (في GitHub Actions أو محلياً).

    python pack_from_spec.py <pack.json> <مجلد المدخلات> <onnxruntime-web/dist> <ناتج.zip>

النموذج ذو ملف الأوزان المنفصل (`model_data`) يُعاد اسماهما إلى ما يشير
إليه النموذج (model.onnx · model.onnx_data) في مجلدٍ مؤقت قبل البناء.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
inp, dist, out = Path(sys.argv[2]), sys.argv[3], sys.argv[4]
here = Path(__file__).resolve().parent
model = inp / spec["model"]
if spec.get("model_data"):
    tmp = Path(tempfile.mkdtemp(prefix="vmodel_"))
    shutil.copy(model, tmp / "model.onnx")
    shutil.copy(inp / spec["model_data"], tmp / "model.onnx_data")
    model = tmp / "model.onnx"
args = [sys.executable, str(here / "build_pack.py"), str(model), dist, out,
        "--id", spec["id"], "--input", str(spec["input"]), "--skip", str(spec["skip"]),
        "--pool", spec["pool"], "--output", spec.get("output", "last_hidden_state"),
        "--mean", ",".join(map(str, spec["mean"])), "--std", ",".join(map(str, spec["std"])),
        "--views", json.dumps(spec["views"]), "--query", json.dumps(spec["query"]),
        "--agg", spec["agg"], "--thr", json.dumps(spec["thr"]),
        "--batch", str(spec.get("batch", 4))]
for lic in spec.get("licenses", []):
    args += ["--license", str(inp / lic)]
if spec.get("fp16_weights"):
    args.append("--fp16-weights")
sys.exit(subprocess.call(args))
