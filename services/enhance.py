# -*- coding: utf-8 -*-
"""محسّن صور الموديلات (4.63) — رسوماتٌ ممسوحة واضحةٌ بارزة، بـQt وحده.

**لماذا مسارٌ خاص بالرسومات**: صور الدليل في الغالب رسوماتٌ بالقلم على
ورق، ممسوحةٌ أو مصوّرة: خطوطٌ رفيعة جداً، وأحجارٌ صغيرة، وظلٌّ رمادي
فاتح يعطي القطعة شكلها. أداة إزالة الخلفية (`services.cutout`) صُنعت
لصورة قطعةٍ على خلفية — فكانت تحسب على نسخةٍ مصغّرة فتذوب الخطوط
الرفيعة، وتعدّ الظلّ الفاتح «فتحاتٍ» في الخلفية فتمحوه: فخرجت الرسومات
منقّطةً باهتة، وبعضها فارغاً.

هنا الرسم يُعالَج **بدقّته الكاملة** وبطريقة الطباعة نفسها:
  1. **الورق أبيض ناصع**: يُقرأ لون الورق من الصورة، وما كان مثله يصير
     أبيض (أو شفافاً) — فيزول اصفراره وبقعه الخفيفة.
  2. **الخط والظل أوضح**: منحنى إضاءةٍ يُغمّق الخط الباهت ويُبقي درجات
     الظلّ كما هي — والقوة تُضبط تلقائياً: الرسم الباهت يُقوّى كثيراً،
     والرسم الواضح أصلاً لا يُمسّ إلا قليلاً (لا يُحرق).
  3. **الكتابة بالقلم الملوّن** (أرقامٌ بالأزرق أو الأحمر) تُمحى، والرسم
     الرمادي باقٍ — اختياري.
  4. **حافّة الماسح السوداء** (ظلّ الغطاء عند طرف الورقة) تُمحى.
  5. **التناسب**: تُقصّ الصورة على الرسم بهامشٍ صغير، فيملأ الرسم إطاره
     في الدليل والطباعة بدل أن يسبح صغيراً في بياض.
  6. **الشفافية من الإضاءة** لا من حدودٍ مقصوصة: كل درجة رمادٍ تصير
     شفافيةً بقدرها — فيبقى الظلّ ظلاً والخطّ خطاً على أي خلفية.
  7. **تظليل القطعة** (4.64): رسومٌ كثيرة ظُلّل نصف طقمها ونصفه أبيض،
     أو رُسمت حدودها بخطٍّ منقّط. فيُعرف مكان القطع من خطوطها (تُسدّ
     فجوات الخطّ الصغيرة، وكل ما أحاطت به الخطوط داخلٌ في القطعة) ويُملأ
     ما فتح لونه داخلها **برماديٍّ موحّد** — داخل القطع وحدها، لا إطار
     ولا خلفية — والخطّ والفصوص الأغمق باقيةٌ فوقه فتبرز.

والصورة الفوتوغرافية الملوّنة (ذهبٌ على خلفية) تمضي إلى `cutout` كما
كانت. والأصل محفوظ دائماً (`models_catalog`)، وكل معالجةٍ تبدأ منه.
"""
import math
import re
from collections import Counter

from PyQt5 import QtCore, QtGui

from services import cutout as _co

VERSION = 3            # يُسجَّل مع كل صورةٍ معالَجة (تُعاد معالجة الأقدم)
MAX_SIDE = 2000        # الصورة المحفوظة — تكفي A4 بدقّة الطباعة
WORK_SIDE = 900        # التحليل (اللون الغالب، الحوافّ، القصّ) على نسخةٍ أصغر
SHADE_SIDE = 640       # تحليل شكل القطع للتظليل — يكفيه نسخةٌ أصغر
INK = QtGui.QColor(24, 22, 20)   # لون الحبر في الصورة الشفافة

DEFAULTS = {
    "mode": "auto",          # auto · drawing · photo
    "strength": 55,          # قوة الخط والظل (0..100)
    "paper": 50,             # تبييض الورق (0..100)
    "remove_color": True,    # محو الكتابة بالقلم الملوّن
    "remove_edges": True,    # محو حافّة الماسح السوداء
    "despeckle": True,       # محو نقاط الغبار الشاردة
    "shade": 55,             # تظليل القطعة (0 = بلا تظليل .. 100 أغمق)
    "reach": 30,             # سدّ الفراغات في حدود القطعة (0..100)
    "crop": True,            # قصٌّ على الرسم (التناسب)
    "transparent": True,     # خلفية شفافة
    "rotate": 0.0,           # تدويرٌ بالدرجات
    "erase": [],             # ممحاة: [(x, y, r)] نسبةً إلى الأصل (0..1)
}


def options(**kw):
    o = dict(DEFAULTS)
    o["erase"] = []
    o.update({k: v for k, v in kw.items() if k in DEFAULTS})
    return o


def load(path):
    r = QtGui.QImageReader(str(path))
    r.setAutoTransform(True)              # اتجاه صورة الجوال كما التُقطت
    img = r.read()
    if img.isNull():
        raise _co.CutoutError("تعذّرت قراءة الصورة: "
                              + (r.errorString() or ""))
    return img


def _cap(img, side=MAX_SIDE):
    if max(img.width(), img.height()) > side:
        img = img.scaled(side, side, QtCore.Qt.KeepAspectRatio,
                         QtCore.Qt.SmoothTransformation)
    return img


def _on_white(img):
    """الصورة على ورقٍ أبيض (RGB32) — الشفاف يصير أبيض لا أسود."""
    return _co.flatten(img.convertToFormat(QtGui.QImage.Format_ARGB32))\
        .convertToFormat(QtGui.QImage.Format_RGB32)


def _rgb(img):
    """(R, G, B, العرض، الارتفاع) لنسخةٍ RGB32 — بايتاتٌ بسرعة C."""
    img = img.convertToFormat(QtGui.QImage.Format_RGB32)
    w, h = img.width(), img.height()
    data = _co._bytes(img)
    st = img.bytesPerLine()
    if st != w * 4:
        data = b"".join(data[y * st:y * st + w * 4] for y in range(h))
    return data[2::4], data[1::4], data[0::4], w, h


def _gray_bytes(img):
    """بايتات الرمادي بلا حشو الأسطر — (bytes، العرض، الارتفاع)."""
    g = img.convertToFormat(QtGui.QImage.Format_Grayscale8)
    w, h = g.width(), g.height()
    data = _co._bytes(g)
    st = g.bytesPerLine()
    if st != w:
        data = b"".join(data[y * st:y * st + w] for y in range(h))
    return data, w, h


def _gray_image(data, w, h):
    return QtGui.QImage(bytes(data), w, h, w,
                        QtGui.QImage.Format_Grayscale8).copy()


def _work(img, side=WORK_SIDE):
    if max(img.width(), img.height()) <= side:
        return img
    return img.scaled(side, side, QtCore.Qt.KeepAspectRatio,
                      QtCore.Qt.SmoothTransformation)


# ══════════════════════════════════════════════════════════════════
#  رسمٌ أم صورة؟
# ══════════════════════════════════════════════════════════════════

def detect(img):
    """«drawing» لرسمٍ رماديٍّ على ورقٍ فاتح، وإلا «photo»."""
    R, G, B, w, h = _rgb(_work(_on_white(img), 320))
    n = w * h
    colored = sum(1 for r, g, b in zip(R, G, B)
                  if max(r, g, b) - min(r, g, b) > 42)
    border = [(R[i] * 299 + G[i] * 587 + B[i] * 114) // 1000
              for i in _co._border_indices(w, h)]
    border.sort()
    light = border[len(border) // 2] >= 150 if border else False
    return "drawing" if light and colored < 0.06 * n else "photo"


# ══════════════════════════════════════════════════════════════════
#  الممحاة والتدوير
# ══════════════════════════════════════════════════════════════════

def _apply_erase(img, strokes):
    if not strokes:
        return img
    out = img.convertToFormat(QtGui.QImage.Format_RGB32)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor("#ffffff"))
    W, H = out.width(), out.height()
    side = max(W, H)
    for x, y, r in strokes:
        p.drawEllipse(QtCore.QPointF(x * W, y * H), r * side, r * side)
    p.end()
    return out


def _rotate(img, angle):
    a = float(angle or 0) % 360.0
    if abs(a) < 0.05 or abs(a - 360) < 0.05:
        return img
    t = QtGui.QTransform().rotate(a)
    box = t.mapRect(QtCore.QRectF(0, 0, img.width(), img.height()))
    out = QtGui.QImage(int(math.ceil(box.width())), int(math.ceil(box.height())),
                       QtGui.QImage.Format_RGB32)
    out.fill(QtGui.QColor("#ffffff"))      # الأركان الجديدة ورقٌ أبيض
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.translate(out.width() / 2.0, out.height() / 2.0)
    p.rotate(a)
    p.drawImage(QtCore.QPointF(-img.width() / 2.0, -img.height() / 2.0), img)
    p.end()
    return out


# ══════════════════════════════════════════════════════════════════
#  التنظيف: الكتابة الملوّنة وحافّة الماسح
# ══════════════════════════════════════════════════════════════════

def _dilate(mask, w, h, times=1):
    """يمدّ القناع بكسلاً في الجهات الأربع `times` مرة — بسرعة الرسم."""
    img = _morph(_mask_image(mask, w, h), times, True, cross_only=True)
    return bytearray(_gray_bytes(img)[0])


def _color_mask(R, G, B, w, h):
    """الكتابة بالقلم الملوّن (أزرق · أحمر · أخضر) على رسمٍ رمادي."""
    m = bytearray(255 if (max(r, g, b) - min(r, g, b) > 42
                          and min(r, g, b) < 225) else 0
                  for r, g, b in zip(R, G, B))
    return _dilate(m, w, h, 2) if any(m) else m


def _edge_mask(R, G, B, w, h):
    """بقعٌ سوداء مصمتة ملتصقة بطرف الصورة: ظلّ غطاء الماسح.

    الرسم نفسه خطوطٌ لا كتلٌ مصمتة، فما كان مصمتاً كبيراً متصلاً بالطرف
    ليس من القطعة. ويُستثنى ما يمتدّ إلى وسط الصورة (قطعةٌ داكنة كبيرة).
    """
    n = w * h
    dark = bytearray(1 if (r * 299 + g * 587 + b * 114) < 70000 else 0
                     for r, g, b in zip(R, G, B))
    seen = bytearray(n)
    out = bytearray(n)
    for s in _co._border_indices(w, h):
        if not dark[s] or seen[s]:
            continue
        comp = [s]
        seen[s] = 1
        k = 0
        x0 = x1 = s % w
        y0 = y1 = s // w
        while k < len(comp):
            i = comp[k]
            k += 1
            x, y = i % w, i // w
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1,
                      i - w, i + w):
                if 0 <= j < n and dark[j] and not seen[j]:
                    seen[j] = 1
                    comp.append(j)
        area = len(comp)
        bbox = (x1 - x0 + 1) * (y1 - y0 + 1)
        central = (x0 > w * 0.3 and x1 < w * 0.7) or \
            (y0 > h * 0.3 and y1 < h * 0.7)
        if area >= n * 0.003 and area >= bbox * 0.45 and not central:
            for i in comp:
                out[i] = 255
    return _dilate(out, w, h, 2) if any(out) else out


def _paint_white(img, mask, w, h):
    """يبيّض ما في القناع (المحسوب على النسخة الصغيرة) بدقّة الأصل."""
    m = _gray_image(mask, w, h).scaled(
        img.width(), img.height(), QtCore.Qt.IgnoreAspectRatio,
        QtCore.Qt.SmoothTransformation).convertToFormat(
        QtGui.QImage.Format_Grayscale8)
    white = QtGui.QImage(img.size(), QtGui.QImage.Format_ARGB32)
    white.fill(QtGui.QColor("#ffffff"))
    white.setAlphaChannel(m)
    out = img.convertToFormat(QtGui.QImage.Format_RGB32)
    p = QtGui.QPainter(out)
    p.drawImage(0, 0, white)
    p.end()
    return out


# ══════════════════════════════════════════════════════════════════
#  المستويات: ورقٌ أبيض، وخطٌّ وظلٌّ واضحان
# ══════════════════════════════════════════════════════════════════

def _levels(hist, total, strength, paper, full_hist=None):
    """(نقطة الأبيض، نقطة الحبر، غامّا).

    · **الأبيض** = لون الورق (أكثر درجةٍ تكراراً في النصف الفاتح) ناقص
      هامشٍ يضبطه «تبييض الورق» — فالورق وبقعه الخفيفة أبيض ناصع.
    · **الحبر** = أغمق الخطوط **بالدقّة الكاملة** (2% الأغمق من الحبر):
      يصير أسود. فالرسم الباهت يصير خطّه أسود واضحاً، والرسم الواضح أصلاً
      لا يتغيّر خطّه — والخطوط الرفيعة لا تذوب في نسخةٍ مصغّرة.
    · **الغامّا** من «قوة الخط والظل»: تُغمّق درجات الظلّ الوسطى باعتدال
      فيبرز الظلّ ولا يبتلع الخطوط.
    """
    best, pk = -1, 235
    for v in range(140, 256):
        s = sum(hist.get(u, 0) for u in range(v - 3, v + 4))
        if s > best:
            best, pk = s, v
    white = max(110, int(round(pk - (4 + paper * 0.2))))
    fh = full_hist or hist
    ink = [(v, c) for v, c in fh.items() if v < white - 18]
    n_ink = sum(c for _, c in ink)
    black = white - 70
    if n_ink:
        acc, need = 0, n_ink * 0.02
        for v, c in sorted(ink):
            acc += c
            if acc >= need:
                black = v
                break
    black = max(0, min(black, white - 40))
    gamma = 1.0 + max(0.0, min(100.0, strength)) / 140.0
    return white, black, gamma


def _lut(white, black, gamma):
    span = float(max(1, white - black))
    out = bytearray(256)
    for v in range(256):
        t = min(1.0, max(0.0, (v - black) / span))
        out[v] = int(round(255 * (t ** gamma)))
    return bytes(out)


def _ink_box(gray, w, h, thr=225):
    """حدود الرسم بلا اعتدادٍ بنقطةٍ شاردة في الطرف."""
    rows = [0] * h
    cols = [0] * w
    for y in range(h):
        row = gray[y * w:(y + 1) * w]
        c = 0
        for x, v in enumerate(row):
            if v < thr:
                cols[x] += 1
                c += 1
        rows[y] = c
    total = sum(rows)
    if not total:
        return None

    def _span(arr):
        lo_need, hi_need = total * 0.002, total * 0.998
        acc, a, b = 0, 0, len(arr) - 1
        for i, c in enumerate(arr):
            acc += c
            if acc >= lo_need:
                a = i
                break
        acc = 0
        for i, c in enumerate(arr):
            acc += c
            if acc >= hi_need:
                b = i
                break
        return a, b
    x0, x1 = _span(cols)
    y0, y1 = _span(rows)
    return x0, y0, x1, y1


def _speck_mask(gray, w, h, thr=170):
    """نقاط الغبار: نقطةٌ داكنة صغيرة جداً لا حبر حولها.

    حجر «البافيه» الصغير متصلٌ بخطوط القطعة أو محاطٌ بها، فلا يُمسّ؛
    والمحذوف ما كان معزولاً في الورق وحده (غبار الماسح ونقاطه).
    """
    n = w * h
    ink = bytearray(1 if v < thr else 0 for v in gray)
    seen = bytearray(n)
    out = bytearray(n)
    max_area = max(3, int(n * 0.000012))
    R = 6
    for s0 in range(n):
        if not ink[s0] or seen[s0]:
            continue
        comp = [s0]
        seen[s0] = 1
        k = 0
        big = False
        while k < len(comp):
            i = comp[k]
            k += 1
            x = i % w
            for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1,
                      i - w, i + w):
                if 0 <= j < n and ink[j] and not seen[j]:
                    seen[j] = 1
                    comp.append(j)
            if len(comp) > max_area:
                big = True
        if big:
            continue
        xs = [i % w for i in comp]
        ys = [i // w for i in comp]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        own = set(comp)
        lonely = True
        for y in range(max(0, y0 - R), min(h, y1 + R + 1)):
            row = y * w
            for x in range(max(0, x0 - R), min(w, x1 + R + 1)):
                if ink[row + x] and (row + x) not in own:
                    lonely = False
                    break
            if not lonely:
                break
        if lonely:
            for i in comp:
                out[i] = 255
    return _dilate(out, w, h, 1) if any(out) else out


# ══════════════════════════════════════════════════════════════════
#  تظليل القطعة: رماديٌّ موحّد داخل قطع الطقم وحدها
# ══════════════════════════════════════════════════════════════════

def _mask_image(mask, w, h):
    """قناعٌ (0/255) صورةً RGB32 — يُرسم عليها بـQPainter."""
    return _gray_image(mask, w, h).convertToFormat(QtGui.QImage.Format_RGB32)


def _morph(img, steps, grow, cross_only=False):
    """تمديدٌ (grow) أو تآكلٌ لقناعٍ أبيض بقرصٍ نصف قطره `steps`.

    كل خطوةٍ إزاحاتٌ بكسلٍ واحد تُدمج بـLighten (الأكبر) أو Darken
    (الأصغر) — بسرعة الرسم لا بحلقة بايثون. وتتناوب الخطوات بين مربّعٍ
    وصليب فيقترب الشكل من القرص (ثماني) فلا تخرج الزوايا مربّعة؛
    و`cross_only` للجهات الأربع وحدها (المعيّن).
    """
    mode = (QtGui.QPainter.CompositionMode_Lighten if grow
            else QtGui.QPainter.CompositionMode_Darken)
    square = (((-1, 0), (1, 0)), ((0, -1), (0, 1)))
    cross = (((-1, 0), (1, 0), (0, -1), (0, 1)),)
    for k in range(steps):
        for offs in (square if k % 2 == 0 and not cross_only else cross):
            src = img.copy()
            p = QtGui.QPainter(img)
            p.setCompositionMode(mode)
            for dx, dy in offs:
                p.drawImage(dx, dy, src)
            p.end()
    return img


_RUNS = re.compile(rb"\x01+")


def _outside(free, w, h, big):
    """الفراغ خارج القطع: المتصل بطرف الصورة، أو الواسع جداً.

    `free` بايتٌ لكل بكسل (1 = فراغ). يُقسَّم كل سطرٍ إلى مقاطع متصلة
    (بسرعة C) وتُجمع المقاطع المتلامسة بين سطرين — فالعمل بعدد المقاطع
    لا بعدد البكسلات. والفراغ المحاط بالقطعة (داخل حجرٍ أو بين خطوطها)
    ليس من الخارج — إلا إن اتّسع (`big`): داخل عقدٍ أو إسوارةٍ مغلقة.
    """
    runs = []
    first = [0] * (h + 1)
    for y in range(h):
        first[y] = len(runs)
        base = y * w
        for m in _RUNS.finditer(free, base, base + w):
            runs.append((y, m.start() - base, m.end() - base))
    first[h] = len(runs)
    parent = list(range(len(runs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for y in range(1, h):
        i, ie = first[y - 1], first[y]
        j, je = first[y], first[y + 1]
        while i < ie and j < je:
            a1, b1 = runs[i][1], runs[i][2]
            a2, b2 = runs[j][1], runs[j][2]
            if a1 < b2 and a2 < b1:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
            if b1 < b2:
                i += 1
            else:
                j += 1
    area = {}
    edge = set()
    for k, (y, a, b) in enumerate(runs):
        r = find(k)
        area[r] = area.get(r, 0) + b - a
        if y == 0 or y == h - 1 or a == 0 or b == w:
            edge.add(r)
    out = bytearray(w * h)
    for k, (y, a, b) in enumerate(runs):
        r = find(k)
        if r in edge or area[r] > big:
            out[y * w + a:y * w + b] = b"\xff" * (b - a)
    return out


def _shade_mask(gray, w, h, reach):
    """مكان القطع (0/255): الحبر وما أحاط به — بلا الورق حولها.

    الحبر يُمدَّد بقدر «سدّ الفراغات» فتنغلق الخطوط المنقّطة والفجوات
    الصغيرة في حدود القطعة، ثم يُعدّ كل ما لا يصل إليه الورق الخارجي
    داخلاً في القطعة، ثم يُعاد التمديد كما كان فترجع الحدود إلى خطّها.
    """
    r = max(1, int(round(1 + reach * 0.08 * max(w, h) / 640.0)))
    ink = gray.translate(bytes(255 if v < 232 else 0 for v in range(256)))
    if not any(ink):
        return None
    closed, _w, _h = _gray_bytes(_morph(_mask_image(ink, w, h), r, True))
    free = closed.translate(bytes(1 if v < 128 else 0 for v in range(256)))
    out = _outside(free, w, h, w * h * 0.025)
    inside = out.translate(bytes(255 - v for v in range(256)))
    sil, _w, _h = _gray_bytes(_morph(_mask_image(inside, w, h), r, False))
    return sil


def _apply_shade(gfull, W, H, sil, sw, sh, tone):
    """يُنزل ما فتح لونه داخل القطع إلى درجة الظلّ — والخطّ الأغمق باقٍ."""
    m = _gray_image(sil, sw, sh).scaled(
        W, H, QtCore.Qt.IgnoreAspectRatio,
        QtCore.Qt.SmoothTransformation).convertToFormat(
        QtGui.QImage.Format_Grayscale8)
    grey = QtGui.QImage(W, H, QtGui.QImage.Format_ARGB32)
    grey.fill(QtGui.QColor(tone, tone, tone))
    grey.setAlphaChannel(m)
    base = _gray_image(gfull, W, H).convertToFormat(QtGui.QImage.Format_RGB32)
    p = QtGui.QPainter(base)
    p.setCompositionMode(QtGui.QPainter.CompositionMode_Darken)
    p.drawImage(0, 0, grey)
    p.end()
    return _gray_bytes(base)[0]


def shade_tone(shade):
    """درجة الرمادي داخل القطع من «تظليل القطعة» (55 ← 184 كرسم C37)."""
    return max(110, min(250, int(round(250 - float(shade) * 1.2))))


def _crop_rect(box, sw, sh, W, H, margin=0.04):
    x0, y0, x1, y1 = box
    sx, sy = W / float(sw), H / float(sh)
    x0, x1 = x0 * sx, (x1 + 1) * sx
    y0, y1 = y0 * sy, (y1 + 1) * sy
    pad = margin * max(x1 - x0, y1 - y0)
    a, b = max(0, int(x0 - pad)), max(0, int(y0 - pad))
    c, d = min(W, int(math.ceil(x1 + pad))), min(H, int(math.ceil(y1 + pad)))
    return QtCore.QRect(a, b, max(1, c - a), max(1, d - b))


def enhance_drawing(img, o):
    """الرسم الممسوح واضحاً بارزاً — (QImage، وصف)."""
    notes = []
    work = _work(img)
    R, G, B, w, h = _rgb(work)
    if o.get("remove_color"):
        m = _color_mask(R, G, B, w, h)
        if any(m):
            img = _paint_white(img, m, w, h)
            notes.append("مُحيت الكتابة الملوّنة")
    if o.get("remove_edges"):
        m = _edge_mask(R, G, B, w, h)
        if any(m):
            img = _paint_white(img, m, w, h)
            notes.append("مُحيت حافّة الماسح السوداء")

    gw, sw, sh = _gray_bytes(_work(img))
    hist = Counter(gw)
    white, black, gamma = _levels(hist, len(gw), float(o.get("strength", 55)),
                                  float(o.get("paper", 50)))
    lut = _lut(white, black, gamma)
    if o.get("despeckle", True):
        m = _speck_mask(gw.translate(lut), sw, sh)
        if any(m):
            img = _paint_white(img, m, sw, sh)
            gw, sw, sh = _gray_bytes(_work(img))
            notes.append("نُظّفت نقاط الغبار")
    gfull, W, H = _gray_bytes(img)
    # نقطة الحبر من الدقّة الكاملة: الخطّ الرفيع لا يُقاس بعد تصغيره
    white, black, gamma = _levels(hist, len(gw), float(o.get("strength", 55)),
                                  float(o.get("paper", 50)), Counter(gfull))
    lut = _lut(white, black, gamma)
    gfull = gfull.translate(lut)
    gsmall = gw.translate(lut)
    shade = float(o.get("shade", 0) or 0)
    if shade > 0:
        gs, xw, xh = _gray_bytes(_work(img, SHADE_SIDE))
        sil = _shade_mask(gs.translate(lut), xw, xh,
                          float(o.get("reach", 30)))
        if sil is not None and any(sil):
            tone = shade_tone(shade)
            gfull = _apply_shade(gfull, W, H, sil, xw, xh, tone)
            notes.append("ظُلّلت القطع")

    if o.get("transparent", True):
        inv = bytes(255 - v for v in range(256))
        alpha = _gray_image(gfull.translate(inv), W, H)
        out = QtGui.QImage(W, H, QtGui.QImage.Format_ARGB32)
        out.fill(INK)
        out.setAlphaChannel(alpha)
    else:
        out = _gray_image(gfull, W, H).convertToFormat(
            QtGui.QImage.Format_RGB32)
    if o.get("crop", True):
        box = _ink_box(gsmall, sw, sh)
        if box is None:
            raise _co.CutoutError("لم يبقَ في الصورة رسمٌ بعد تبييض الورق —"
                                  " خفّف «تبييض الورق»")
        out = out.copy(_crop_rect(box, sw, sh, W, H))
    notes.insert(0, "رسمٌ أوضح وورقٌ أبيض"
                 + (" شفاف" if o.get("transparent", True) else ""))
    return out, " · ".join(notes)


def process(img, opts=None):
    """يحسّن صورة موديل بحسب الخيارات — (QImage، الوضع، وصف).

    يرفع `cutout.CutoutError` بسببٍ مقروء إن تعذّر (صورةٌ فوتوغرافية على
    خلفيةٍ مزدحمة مثلاً) — والصورة تبقى كما هي.
    """
    o = options(**(opts or {}))
    img = _cap(img)
    img = _apply_erase(_on_white(img), o.get("erase"))
    img = _rotate(img, o.get("rotate"))
    mode = o.get("mode") or "auto"
    if mode == "auto":
        mode = detect(img)
    if mode == "drawing":
        out, note = enhance_drawing(img, o)
        return out, mode, note
    if not o.get("transparent", True):
        if o.get("crop", True):
            try:
                keep, w, h, _n, _b, _t = _co.mask_of(img)
                box = _co._bbox(keep, w, h)
                if box:
                    img = img.copy(_crop_rect(box, w, h, img.width(),
                                              img.height(), 0.03))
            except _co.CutoutError:
                pass
        return img, mode, "صورةٌ كما هي (بخلفيتها)"
    out, note = _co.cutout(img)
    return out, mode, note


def process_file(src, dst, opts=None):
    out, mode, note = process(load(src), opts)
    if not out.save(str(dst), "PNG"):
        raise _co.CutoutError("تعذّر حفظ الصورة بعد تحسينها")
    return mode, note
