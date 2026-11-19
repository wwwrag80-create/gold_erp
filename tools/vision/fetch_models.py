# -*- coding: utf-8 -*-
"""يجلب نماذج «البحث بالصورة» المرشّحة من Hugging Face (في GitHub Actions).

جلسة التطوير لا تصل إلى Hugging Face، فيجلبها مشغّل GitHub ويضعها في إصدار
`vision-models` (للتقييم وحده) — ومنه تُنزَّل للتجربة والمقارنة.

    python tools/vision/fetch_models.py <مجلد-الناتج>

لكل مستودع: قائمة ملفاته من واجهة HF، ثم تنزيل ما يطابق الأنماط. والمستودع
الذي لا يوجد أو يحتاج إذناً يُتخطّى بسطرٍ يقول ذلك — لا يوقف الباقي.
"""
import fnmatch
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HF = "https://huggingface.co"

# (المستودع، الأنماط) — مشفّرات الصور وحدها، بلا النصوص
CANDIDATES = [
    ("Xenova/dinov2-small", ["onnx/model.onnx", "onnx/model_quantized.onnx",
                             "onnx/model_fp16.onnx", "preprocessor_config.json",
                             "config.json"]),
    ("Xenova/dinov2-base", ["onnx/model_quantized.onnx", "onnx/model_fp16.onnx",
                            "preprocessor_config.json"]),
    ("onnx-community/dinov2-with-registers-small",
     ["onnx/model.onnx", "onnx/model_quantized.onnx", "onnx/model_fp16.onnx",
      "preprocessor_config.json"]),
    ("onnx-community/dinov2-with-registers-base",
     ["onnx/model_quantized.onnx", "onnx/model_fp16.onnx",
      "preprocessor_config.json"]),
    ("Xenova/clip-vit-base-patch32", ["onnx/vision_model.onnx",
                                      "onnx/vision_model_quantized.onnx",
                                      "onnx/vision_model_fp16.onnx",
                                      "preprocessor_config.json"]),
    ("Xenova/clip-vit-base-patch16", ["onnx/vision_model_quantized.onnx",
                                      "onnx/vision_model_fp16.onnx",
                                      "preprocessor_config.json"]),
    ("Xenova/siglip-base-patch16-224", ["onnx/vision_model_quantized.onnx",
                                        "onnx/vision_model_fp16.onnx",
                                        "preprocessor_config.json"]),
    ("Xenova/mobileclip_s0", ["onnx/vision_model.onnx",
                              "onnx/vision_model_quantized.onnx",
                              "preprocessor_config.json", "LICENSE*",
                              "README.md"]),
    ("Xenova/mobileclip_s2", ["onnx/vision_model_quantized.onnx",
                              "onnx/vision_model_fp16.onnx",
                              "preprocessor_config.json"]),
    ("onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX",
     ["onnx/model.onnx", "onnx/model.onnx_data", "onnx/model_quantized.onnx",
      "onnx/model_quantized.onnx_data", "preprocessor_config.json",
      "LICENSE*", "README.md"]),
    ("onnx-community/dinov3-vitb16-pretrain-lvd1689m-ONNX",
     ["onnx/model_quantized.onnx", "onnx/model_quantized.onnx_data",
      "preprocessor_config.json"]),
]


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "model-fetch"})
    return urllib.request.urlopen(req, timeout=timeout)


def files_of(repo):
    with _get(f"{HF}/api/models/{repo}?blobs=true") as r:
        d = json.load(r)
    lic = (d.get("cardData") or {}).get("license") or ""
    gated = d.get("gated")
    return {s["rfilename"]: s.get("size") for s in d.get("siblings", [])}, \
        lic, gated


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for repo, pats in CANDIDATES:
        try:
            files, lic, gated = files_of(repo)
        except Exception as e:
            print(f"✘ {repo}: {e}")
            continue
        print(f"── {repo}  license={lic or '?'}  gated={gated}")
        onnx = sorted(f for f in files if f.startswith("onnx/"))
        print("   onnx files:", ", ".join(onnx[:30]))
        for name in files:
            if not any(fnmatch.fnmatch(name, p) for p in pats):
                continue
            dst = out / (repo.replace("/", "__") + "__"
                         + name.replace("/", "__"))
            try:
                h = hashlib.sha256()
                with _get(f"{HF}/{repo}/resolve/main/{name}", 600) as r, \
                        open(dst, "wb") as fh:
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        h.update(b)
                        fh.write(b)
                rows.append({"repo": repo, "file": name, "asset": dst.name,
                             "size": dst.stat().st_size,
                             "sha256": h.hexdigest(), "license": lic})
                print(f"   ✔ {name}  {dst.stat().st_size / 1e6:.1f} MB")
            except Exception as e:
                print(f"   ✘ {name}: {e}")
                dst.unlink(missing_ok=True)
    (out / "models.json").write_text(json.dumps(rows, indent=1),
                                     encoding="utf-8")
    print(f"\n{len(rows)} ملفاً")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "vision_models")
