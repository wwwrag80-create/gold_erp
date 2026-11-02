"""فيديو تعليمي — مقطعٌ قصير لكل فصل (للإرسال في واتساب حسب الحاجة).

    python3 mobile/tools/video/chapters.py VIDEO.mp4 TIMELINE.json OUT_DIR

يقصّ الفيديو الكامل عند حدود الفصول (من بطاقة الفصل إلى ما قبل التالي)، بمقاس
720×1280، مع ظهورٍ واختفاءٍ هادئين للصورة والصوت.
"""
import json
import subprocess
import sys
from pathlib import Path

VIDEO, TL, OUT = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
segs = TL["segments"]
chs = [s for s in segs if s["type"] == "chapter"]
outro = next(s for s in segs if s["type"] == "outro")
for i, c in enumerate(chs):
    a = max(0.0, c["start"] - 0.1)
    b = chs[i + 1]["start"] if i + 1 < len(chs) else outro["start"]
    d = b - a
    name = OUT / f"دليل-{c['n']:02d}-{c['title'].replace(' ', '-')}.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{a:.3f}", "-i", str(VIDEO), "-t", f"{d:.3f}",
                    "-vf", f"scale=720:1280:flags=lanczos,fade=t=in:st=0:d=0.3,fade=t=out:st={d - 0.5:.3f}:d=0.5",
                    "-af", f"afade=t=in:st=0:d=0.3,afade=t=out:st={d - 0.6:.3f}:d=0.6",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-profile:v", "main",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(name)], check=True)
    print(f"  ✔ {name.name} — {d:.0f} ث")
