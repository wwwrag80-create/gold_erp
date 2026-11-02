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
import os
import subprocess

# «هادئ» (الدليل الكامل): أبطأ قليلاً لمن يتعلّم. «مفعم» (TTS_STYLE=lively): أسرع،
# ونبرةٌ أكثر تنوّعاً، ثم رفعٌ يسير للطبقة ووضوحٌ في الصوت. «طبيعي» (TTS_STYLE=natural):
# إيقاعٌ وتنغيمٌ أحرّ كالكلام البشري، بلا تغييرٍ للطبقة، وحضورٌ خفيف وصدى غرفةٍ يسير
STYLE = os.environ.get("TTS_STYLE", "")
SC = {"lively": SynthesisConfig(length_scale=0.88, noise_scale=0.75, noise_w_scale=0.85),
      "natural": SynthesisConfig(length_scale=0.82, noise_scale=0.8, noise_w_scale=1.0)}.get(
    STYLE, SynthesisConfig(length_scale=1.06, noise_scale=0.55, noise_w_scale=0.7))
POST = {"lively": "asetrate=22050*1.05,aresample=22050,atempo=0.9524,"
                  "equalizer=f=3000:t=q:w=1.2:g=3,equalizer=f=180:t=q:w=1:g=-2,"
                  "acompressor=threshold=-20dB:ratio=3:attack=5:release=80:makeup=2",
        # (يُقصّ الصمت الزائد أول المقطع وآخره، فيتّصل الكلام كحديثٍ واحد)
        "natural": "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.05,areverse,"
                   "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.1,areverse,"
                   "highpass=f=70,equalizer=f=220:t=q:w=1:g=1.5,equalizer=f=2800:t=q:w=1.4:g=2,"
                   "equalizer=f=7500:t=q:w=1:g=-2,acompressor=threshold=-22dB:ratio=2.2:attack=8:release=120:makeup=1.5,"
                   "aecho=0.8:0.6:24|41:0.1|0.06"}.get(STYLE)
if os.environ.get("TTS_LENGTH"):           # سرعةٌ أخرى لصوتٍ أسرع أو أبطأ بطبعه (1 = سرعته الأصلية)
    SC.length_scale = float(os.environ["TTS_LENGTH"])
# TTS_TAG=x يكتب voice_x/ و voice_x.json (صوتٌ بديل للمقارنة) بدل voice/ و voice.json
TAG = os.environ.get("TTS_TAG", "")

m = json.loads((SHOTS / "manifest.json").read_text(encoding="utf-8"))
items = [(k, m["meta"][k]) for k in ("intro", "outro") if m["meta"].get(k)]
b = m["meta"].get("benefits")
if b:
    items.append(("benefits_q", b["say"]))
    items += [(f"benefit_{i + 1}", it["say"]) for i, it in enumerate(b["items"])]
    items.append(("benefits_end", b["end"]["say"]))
for s in m["shots"]:
    if s.get("say"):
        items.append((f"ch{s['n']}" if s["type"] == "chapter" else s["file"][:-4], s["say"]))

out = SHOTS / ("voice_" + TAG if TAG else "voice")
out.mkdir(exist_ok=True)
info = {}
for key, text in items:
    f = out / f"{key}.wav"
    with wave.open(str(f), "wb") as w:
        voice.synthesize_wav(text, w, syn_config=SC)
    if POST:
        tmp = f.with_suffix(".raw.wav")
        f.rename(tmp)
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(tmp), "-af", POST,
                        "-ar", "22050", "-ac", "1", "-c:a", "pcm_s16le", str(f)], check=True)
        tmp.unlink()
    with wave.open(str(f)) as r:
        info[key] = {"file": str(f), "dur": round(r.getnframes() / r.getframerate(), 3)}
    print(f"  ✔ {key}: {info[key]['dur']} ث")
(SHOTS / ("voice_" + TAG + ".json" if TAG else "voice.json")).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"✔ {len(info)} مقطعاً صوتياً · {sum(v['dur'] for v in info.values()):.0f} ث")
