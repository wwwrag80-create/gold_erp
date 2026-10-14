"""الإطارات (PNG بعمق 16 بت) ← حلقة WebP متحرّكة + صورةٌ ساكنة بديلة.

  · التحويل إلى 8 بت بارتعاشٍ مثلّثي خفيف (±1 درجة) ثابتِ النمط: يمنع
    التدرّج المتدرّج (banding) في ظلال الأرضية وتوهّج الأفق، وثباته بين
    الإطارات يمنع «الغليان» الزمني.
  · WebP بجودة عالية وأبطأ طريقةٍ للضغط (أدقّ نتيجة)، ومدّة الإطار 33 م.ث
    (30 إطاراً/ث)، وحلقةٌ لا تنتهي.

الاستخدام: python encode2.py FRAMES_DIR OUT.webp POSTER.jpg [QUALITY] [DITHER]
"""
import glob
import os
import sys

import cv2
import numpy as np
from PIL import Image

src, out_webp, out_jpg = sys.argv[1], sys.argv[2], sys.argv[3]
q = int(sys.argv[4]) if len(sys.argv) > 4 else 90
dither = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
files = sorted(glob.glob(os.path.join(src, "f*.png")))
if os.environ.get("LIMIT"):
    files = files[:int(os.environ["LIMIT"])]

_noise = None


def load(path):
    global _noise
    a = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    a = cv2.cvtColor(a, cv2.COLOR_BGR2RGB)
    if a.dtype == np.uint16:
        f = a.astype(np.float32) * (255.0 / 65535.0)
        if dither > 0:
            if _noise is None or _noise.shape != f.shape:
                rng = np.random.default_rng(7)
                # مثلّثي: مجموع منتظمَين — لا يترك نمطاً ولا يغيّر المتوسّط
                _noise = (rng.random(f.shape, dtype=np.float32)
                          + rng.random(f.shape, dtype=np.float32) - 1.0) * dither
            f = f + _noise
        a = np.clip(np.rint(f), 0, 255).astype(np.uint8)
    return Image.fromarray(a, "RGB")


frames = [load(f) for f in files]
frames[0].save(out_jpg, "JPEG", quality=92, optimize=True, progressive=True,
               subsampling=0)
frames[0].save(out_webp, "WEBP", save_all=True, append_images=frames[1:],
               duration=33, loop=0, quality=q, method=6, minimize_size=False,
               allow_mixed=False)
print(len(frames), "frames", os.path.getsize(out_webp) // 1024, "KB webp,",
      os.path.getsize(out_jpg) // 1024, "KB poster")
