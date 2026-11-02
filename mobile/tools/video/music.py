"""فيديو تعليمي — الخطوة 3: موسيقى هادئة ومؤثرات مُركَّبة، ومعها الصوت الشارح.

    python3 mobile/tools/video/music.py OUT_DIR

يقرأ OUT_DIR/timeline.json (من render.js) ويكتب OUT_DIR/music.wav:
خلفيةٌ هادئة (أوتارٌ ممتدة + نقراتٌ كالقانون) في لا الصغير، ونقرةٌ خفيفة عند كل
لمسة، وهبّةٌ ناعمة عند كل فصل، ولمعةٌ في المقدّمة والختام. كلّها مُولَّدة رياضياً.
"""
import json
import math
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
TL = json.loads((OUT / "timeline.json").read_text(encoding="utf-8"))
T = TL["total"] + 0.6
N = int(T * SR)
t = np.arange(N) / SR
rng = np.random.default_rng(7)

L = np.zeros(N)
R = np.zeros(N)


def note(name):
    names = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    n, octv = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((names[n] + 12 * (octv - 4)) / 12)


def add(buf, start, sig):
    i = int(start * SR)
    if i >= N:
        return
    j = min(N, i + len(sig))
    buf[i:j] += sig[: j - i]


# ── الأوتار الممتدة: لا الصغير ← فا ← دو ← مي الصغير، لكل وترٍ مازورتان ──
CHORDS = [
    ["A2", "E3", "A3", "B3", "C4", "E4"],
    ["F2", "C3", "F3", "A3", "C4", "E4"],
    ["C3", "G3", "C4", "D4", "E4", "G4"],
    ["E2", "B2", "E3", "G3", "B3", "D4"],
]
BPM = float(TL.get("bpm") or 72)
CH_LEN = 8 * 60 / BPM
pad = np.zeros(N)
bass = np.zeros(N)
nchords = int(T / CH_LEN) + 2
for k in range(nchords):
    s0 = k * CH_LEN - 1.0
    dur = CH_LEN + 2.2
    n = int(dur * SR)
    tt = np.arange(n) / SR
    env = np.minimum(1, tt / 1.6) * np.minimum(1, np.maximum(0, (dur - tt) / 1.8))
    sig = np.zeros(n)
    for nm in CHORDS[k % 4][1:]:
        f = note(nm)
        sig += np.sin(2 * np.pi * f * tt) + 0.6 * np.sin(2 * np.pi * f * 1.0035 * tt + 1.3)
    sig *= env * 0.022
    root = note(CHORDS[k % 4][0])
    b = (np.sin(2 * np.pi * root * tt) + 0.25 * np.sin(2 * np.pi * 2 * root * tt)) * env * 0.075
    i = int(s0 * SR)
    a = max(0, i)
    j = min(N, i + n)
    if j > a:
        pad[a:j] += sig[a - i: j - i]
        bass[a:j] += b[a - i: j - i]
pad *= 0.9 + 0.1 * np.sin(2 * np.pi * 0.07 * t)


# ── نقرات كالقانون: ثُمنيّات على نغمات الوتر في الأوكتاف الرابع والخامس ──
def pluck(f, dur=1.6, decay=0.55, amp=1.0):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    env = np.minimum(1, tt / 0.004) * np.exp(-tt / decay)
    return amp * env * (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(4 * np.pi * f * tt) + 0.1 * np.sin(6 * np.pi * f * tt))


ARP = [0, 2, 3, 5, 3, 2, 4, 2]
BEAT = 60 / BPM / 2
intro_end = next(s["end"] for s in TL["segments"] if s["type"] == "intro")
outro_start = next(s["start"] for s in TL["segments"] if s["type"] == "outro")
k = 0
x = intro_end - 1.2
while x < T - 3.0:
    ci = int((x + 1.0) // CH_LEN) % 4
    tones = [note(nm) * 2 for nm in CHORDS[ci][1:]]
    f = tones[ARP[k % len(ARP)] % len(tones)]
    amp = 0.05 * (0.8 if k % 2 else 1.0)
    sig = pluck(f, amp=amp)
    pan = 0.35 if k % 2 else -0.35
    add(L, x, sig * (1 - pan))
    add(R, x, sig * (1 + pan))
    k += 1
    x += BEAT

# ── نبضٌ خفيف (للنسخ القصيرة الأسرع): ضربةٌ منخفضة على الأولى والثالثة، وهمسٌ بينهما ──
if BPM >= 90:
    x = intro_end - 0.2
    k = 0
    while x < outro_start + 2.0:
        if k % 4 in (0, 2):
            n = int(0.25 * SR)
            tt = np.arange(n) / SR
            kick = 0.09 * np.exp(-tt / 0.09) * np.sin(2 * np.pi * (48 + 40 * np.exp(-tt / 0.03)) * tt)
            add(L, x, kick)
            add(R, x, kick)
        else:
            n = int(0.06 * SR)
            hat = 0.012 * np.exp(-np.arange(n) / SR / 0.012) * rng.standard_normal(n)
            add(L, x, hat * 0.8)
            add(R, x, hat * 1.2)
        k += 1
        x += 60 / BPM

# ── لمعةٌ في المقدّمة والختام ──
for start in (0.5, outro_start + 0.2):
    for i, nm in enumerate(["E6", "A6", "B6", "E7", "A6"]):
        sig = pluck(note(nm), dur=2.5, decay=0.9, amp=0.035)
        add(L, start + i * 0.12, sig * (1.2 if i % 2 else 0.8))
        add(R, start + i * 0.12, sig * (0.8 if i % 2 else 1.2))

# ── لمعةٌ خفيفة مع كل بطاقةٍ في لوحة الفوائد ──
for s in TL["segments"]:
    if s["type"] == "benefits":
        for i, it in enumerate(s["items"] + [s["fin"]]):
            for j, nm in enumerate(["A6", "E7"] if i < len(s["items"]) else ["E6", "A6", "E7"]):
                sig = pluck(note(nm), dur=2.0, decay=0.7, amp=0.03)
                add(L, s["start"] + it["at"] - 0.1 + j * 0.09, sig)
                add(R, s["start"] + it["at"] - 0.1 + j * 0.09, sig)

# ── المؤثرات: نقرة اللمسة، وهبّة الفصل ──
sfx = np.zeros(N)
for s in TL["segments"]:
    if s["type"] == "shot" and s.get("tapAt") is not None:
        n = int(0.09 * SR)
        tt = np.arange(n) / SR
        click = 0.11 * np.exp(-tt / 0.018) * np.sin(2 * np.pi * 2300 * tt) + 0.07 * np.exp(-tt / 0.03) * np.sin(2 * np.pi * 1150 * tt)
        add(sfx, s["start"] + s["tapAt"], click)
    if s["type"] == "chapter":
        n = int(0.9 * SR)
        noise = rng.standard_normal(n)
        y = np.zeros(n)
        prev = 0.0
        for i in range(n):          # تمريرٌ منخفضٌ يتّسع ثم يضيق
            fc = 250 + 2600 * math.sin(math.pi * i / n) ** 2
            a = 1 - math.exp(-2 * math.pi * fc / SR)
            prev += a * (noise[i] - prev)
            y[i] = prev
        tt = np.arange(n) / SR
        env = np.sin(np.pi * tt / 0.9) ** 2
        boom = 0.12 * np.exp(-tt / 0.45) * np.sin(2 * np.pi * 58 * tt)
        add(sfx, s["start"] - 0.25, 0.10 * y * env + boom)


# ── صدى (ارتدادٌ صناعي) ──
def reverb(x, seconds=2.4, decay=0.55, seed=1):
    m = int(seconds * SR)
    ir = np.random.default_rng(seed).standard_normal(m) * np.exp(-np.arange(m) / SR / decay)
    ir[0] = 0
    ir /= np.sqrt(np.sum(ir ** 2))
    size = 1 << int(math.ceil(math.log2(len(x) + m)))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
    return y


music_mono = pad + bass
L += music_mono
R += music_mono
wetL, wetR = reverb(L, seed=1), reverb(R, seed=2)
L = 0.75 * L + 0.30 * wetL + sfx + 0.12 * reverb(sfx, 1.2, 0.3, 3)
R = 0.75 * R + 0.30 * wetR + sfx + 0.12 * reverb(sfx, 1.2, 0.3, 4)

fade = np.minimum(1, t / 1.5) * np.minimum(1, np.maximum(0, (T - 0.3 - t) / 2.8))
L *= fade
R *= fade
peak = max(np.max(np.abs(L)), np.max(np.abs(R)))
L, R = L / peak * 0.89, R / peak * 0.89

# ── الصوت الشارح (إن وُجد): فوق الموسيقى، والموسيقى تنخفض وهو يتكلّم ──
voices = TL.get("voices") or []
if voices:
    L, R = L * 0.55, R * 0.55
    vo = np.zeros(N)
    on = np.zeros(N)
    for v in voices:
        with wave.open(v["file"]) as w:
            sr = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float64) / 32768
        if w.getnchannels() == 2:
            x = x.reshape(-1, 2).mean(axis=1)
        y = np.interp(np.arange(int(len(x) * SR / sr)) * sr / SR, np.arange(len(x)), x)
        rms = math.sqrt(float(np.mean(y ** 2))) or 1.0
        y *= 0.16 / rms                                   # كل مقطعٍ بالعلوّ نفسه تقريباً
        add(vo, v["at"], y)
        i, j = int(max(0, v["at"] - 0.25) * SR), int(min(T, v["at"] + v["dur"] + 0.45) * SR)
        on[i:j] = 1
    k = int(0.35 * SR)
    win = np.hanning(k)
    duck = np.convolve(on, win / win.sum(), mode="same")
    g = 1 - 0.62 * duck                                   # نحو −8 dB تحت الكلام
    L, R = L * g + vo, R * g + vo
    peak = max(np.max(np.abs(L)), np.max(np.abs(R)))
    if peak > 0.97:
        L, R = L / peak * 0.97, R / peak * 0.97

data = (np.stack([L, R], axis=1) * 32767).astype("<i2").tobytes()
with wave.open(str(OUT / "music.wav"), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(data)
print(f"✔ {OUT / 'music.wav'} — {T:.1f} ث")
