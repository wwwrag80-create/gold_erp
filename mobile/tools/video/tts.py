"""فيديو تعليمي — الصوت: يقرأ نصوص الشرح (مشكولةً) بصوتٍ عربي مُولَّد محلياً.

    python3 mobile/tools/video/tts.py SHOTS_DIR VOICE_DIR

VOICE_DIR فيه صوت Piper العربي «كريم» (ar_JO-kareem-medium.onnx و .onnx.json)،
ويُنزَّل من إصدارات sherpa-onnx على GitHub (vits-piper-ar_JO-kareem-medium).
يكتب SHOTS_DIR/voice/<المفتاح>.wav و SHOTS_DIR/voice.json (مدة كل مقطع)، ويقرؤها
render.js (توقيت المشاهد) و music.py (المزج).
"""
import json
import sys
import wave
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

SHOTS = Path(sys.argv[1])
VOICE = Path(sys.argv[2])
onnx = next(VOICE.glob("*.onnx"))
voice = PiperVoice.load(str(onnx), config_path=str(onnx) + ".json")
# أبطأ قليلاً من المعتاد، وأهدأ نبرة — لمن يتعلّم
SC = SynthesisConfig(length_scale=1.06, noise_scale=0.55, noise_w_scale=0.7)

m = json.loads((SHOTS / "manifest.json").read_text(encoding="utf-8"))
items = [("intro", m["meta"]["intro"]), ("outro", m["meta"]["outro"])]
b = m["meta"].get("benefits")
if b:
    items.append(("benefits_q", b["say"]))
    items += [(f"benefit_{i + 1}", it["say"]) for i, it in enumerate(b["items"])]
    items.append(("benefits_end", b["end"]["say"]))
for s in m["shots"]:
    if s.get("say"):
        items.append((f"ch{s['n']}" if s["type"] == "chapter" else s["file"][:-4], s["say"]))

out = SHOTS / "voice"
out.mkdir(exist_ok=True)
info = {}
for key, text in items:
    f = out / f"{key}.wav"
    with wave.open(str(f), "wb") as w:
        voice.synthesize_wav(text, w, syn_config=SC)
    with wave.open(str(f)) as r:
        info[key] = {"file": str(f), "dur": round(r.getnframes() / r.getframerate(), 3)}
    print(f"  ✔ {key}: {info[key]['dur']} ث")
(SHOTS / "voice.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"✔ {len(info)} مقطعاً صوتياً · {sum(v['dur'] for v in info.values()):.0f} ث")
