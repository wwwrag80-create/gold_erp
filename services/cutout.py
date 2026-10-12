# -*- coding: utf-8 -*-
"""إزالة خلفية صور الموديلات (4.61) — بـQt وحده، بلا أي مكتبة إضافية.

صورة الموديل تُلتقط عادةً على خلفيةٍ واحدة (سوداء أو بيضاء أو رمادية).
تلك الخلفية تُطبع مربّعاً داكناً حول القطعة، وتظهر في الدليل والطلبات
والرابط كأن كل صورةٍ في إطار. هنا تُزال: تصير شفافة، وتُقصّ الصورة على
حدود القطعة نفسها — فتكبر القطعة في مكانها وتظهر أوضح.

**كيف** (بلا ذكاءٍ اصطناعي ولا مكتبات):
  1. لون الخلفية يُقرأ من **حوافّ** الصورة: اللون الغالب فيها. فإن لم
     يغلب لونٌ واحد (صورةٌ في محلٍّ مثلاً) لا يُمسّ شيء — ويُقال السبب.
  2. يُملأ من الحوافّ إلى الداخل كلُّ ما يشبه الخلفية متصلاً بها،
     ويُتسامح مع تدرّجها (ظلٌّ أو إضاءة) خطوةً خطوة.
  3. الفتحات الداخلية بلون الخلفية نفسه (وسط الخاتم أو الحلق) تُزال كذلك
     — بتسامحٍ أضيق، فلا يُمسّ لمعان الذهب.
  4. حافّة القطعة تُنعَّم فلا تبدو مقصوصةً بالمقصّ، وتُطرح بقايا لون
     الخلفية العالقة بها.

الأصل لا يضيع: يُحفظ بجانبها (`models_catalog`) ويُستعاد بنقرة.
"""
import re
from collections import deque

from PyQt5 import QtCore, QtGui

MAX_SIDE = 1800        # الصورة المحفوظة — تكفي A4 بدقّة الطباعة
WORK_SIDE = 560        # حساب القناع على نسخةٍ مصغّرة (سرعةٌ بلا فرقٍ يُرى)
MARGIN = 0.03          # هامشٌ حول القطعة بعد القصّ


class CutoutError(ValueError):
    pass


def _bytes(img):
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes() if hasattr(img, "sizeInBytes")
                else img.byteCount())
    return bytes(ptr)


def _border_indices(w, h):
    idx = list(range(w)) + list(range((h - 1) * w, h * w))
    for y in range(1, h - 1):
        idx.append(y * w)
        idx.append(y * w + w - 1)
    return idx


def _dominant(R, G, B, idx):
    """اللون الغالب على الحوافّ ونسبة ما يقاربه منها."""
    buckets = {}
    for i in idx:
        k = (R[i] >> 4, G[i] >> 4, B[i] >> 4)
        buckets[k] = buckets.get(k, 0) + 1
    # الدلو الغالب مع جيرانه المباشرين (لونٌ على حدّ دلوين)
    best, best_n = None, -1
    for k in buckets:
        n = sum(buckets.get((k[0] + a, k[1] + b, k[2] + c), 0)
                for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1))
        if n > best_n:
            best, best_n = k, n
    cr, cg, cb = (best[0] * 16 + 8, best[1] * 16 + 8, best[2] * 16 + 8)
    near = [i for i in idx
            if (R[i] - cr) ** 2 + (G[i] - cg) ** 2 + (B[i] - cb) ** 2
            <= 48 ** 2]
    if not near:
        return (cr, cg, cb), 0.0, 30.0
    n = len(near)
    mr = sum(R[i] for i in near) / n
    mg = sum(G[i] for i in near) / n
    mb = sum(B[i] for i in near) / n
    var = sum((R[i] - mr) ** 2 + (G[i] - mg) ** 2 + (B[i] - mb) ** 2
              for i in near) / n
    return (mr, mg, mb), n / float(len(idx)), var ** 0.5


def _chroma_lum(R, G, B):
    ch = [max(r, g, b) - min(r, g, b) for r, g, b in zip(R, G, B)]
    lu = [(r * 299 + g * 587 + b * 114) // 1000 for r, g, b in zip(R, G, B)]
    return ch, lu


def mask_of(img):
    """قناع القطعة (bytearray: 255 تبقى · 0 خلفية) على نسخةٍ مصغّرة.

    يعيد (القناع، العرض، الارتفاع، وصفاً، لون الخلفية، التسامح) — أو
    يرفع `CutoutError`.

    **الذهب لا يُؤكل مع الخلفية**: الخلفيات رمادية أو سوداء أو بيضاء
    (لونها «باهت»)، والذهب لونٌ مشبَع. فالتسامح مع تدرّج الخلفية (ظلٌّ،
    إضاءةٌ من جانب) لا يعبر إلى لونٍ أشبع منها — ولو تشابهت الإضاءة.
    """
    w0, h0 = img.width(), img.height()
    s = min(1.0, WORK_SIDE / float(max(w0, h0)))
    w, h = max(8, int(round(w0 * s))), max(8, int(round(h0 * s)))
    small = img.scaled(w, h, QtCore.Qt.IgnoreAspectRatio,
                       QtCore.Qt.SmoothTransformation).convertToFormat(
        QtGui.QImage.Format_ARGB32)
    data = _bytes(small)
    stride = small.bytesPerLine()
    if stride != w * 4:           # لا يقع لـARGB32، لكن للاحتياط
        data = b"".join(data[y * stride:y * stride + w * 4]
                        for y in range(h))
    B, G, R, A = data[0::4], data[1::4], data[2::4], data[3::4]
    n = w * h
    border = _border_indices(w, h)

    # صورةٌ شفافة الحوافّ أصلاً: قناعها من شفافيّتها، وتُقصّ فقط
    if sum(1 for i in border if A[i] < 24) >= 0.6 * len(border):
        return (bytearray(255 if a >= 24 else 0 for a in A), w, h,
                "الصورة شفافة الخلفية أصلاً — قُصّت على القطعة", None, 0)

    (br, bg, bb), share, spread = _dominant(R, G, B, border)
    if share < 0.42:
        raise CutoutError("خلفية الصورة ليست لوناً واحداً (صورةٌ في محلٍّ"
                          " أو على قماشٍ منقوش) — تُركت كما هي")
    tol = max(24.0, min(56.0, 2.2 * spread + 20.0))
    t1 = tol * tol                       # يشبه الخلفية مباشرةً
    t2 = (tol * 2.0) ** 2                # يقبل التدرّج إن جاوره المشابه
    step2 = 14 ** 2                      # فرق الجارين المسموح في التدرّج
    bc = max(br, bg, bb) - min(br, bg, bb)
    CH = 26                              # فرق «التشبّع» المسموح
    dbg = [(r - br) ** 2 + (g - bg) ** 2 + (b - bb) ** 2
           for r, g, b in zip(R, G, B)]
    ch, lu = _chroma_lum(R, G, B)

    rem = bytearray(n)                   # 1 = خلفية
    q = deque()
    for i in border:
        if dbg[i] <= t1 and not rem[i]:
            rem[i] = 1
            q.append(i)
    while q:
        i = q.popleft()
        x = i % w
        ri, gi, bi = R[i], G[i], B[i]
        for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1,
                  i - w, i + w):
            if j < 0 or j >= n or rem[j]:
                continue
            d = dbg[j]
            if d <= t1 or (d <= t2 and abs(ch[j] - bc) <= CH
                           and (R[j] - ri) ** 2 + (G[j] - gi) ** 2
                           + (B[j] - bi) ** 2 <= step2):
                rem[j] = 1
                q.append(j)

    # ══ الفتحات الداخلية بلون الخلفية (وسط الخاتم والحلق) ══
    # تُعرف بلونها لا بموضعها: باهتةٌ كالخلفية، وإضاءتها في مدى إضاءة
    # الخلفية التي أُزيلت فعلاً (فوسط خاتمٍ على خلفيةٍ متدرّجة يُزال).
    lum_bg = sorted(lu[i] for i in range(n) if rem[i])
    if lum_bg:
        # هامشٌ أوسع فوق أفتح الخلفية: الإضاءة تتركّز عادةً في وسط
        # الصورة — حيث فتحة الخاتم — فيكون وسطها أفتح من حوافّها
        lo = lum_bg[int(len(lum_bg) * 0.02)] - 20
        hi = lum_bg[int(len(lum_bg) * 0.98) - 1 if len(lum_bg) > 1 else 0] + 30
    else:
        lo = hi = -1
    th = (tol * 0.6) ** 2

    def _holeish(i):
        return dbg[i] <= th or (abs(ch[i] - bc) <= 18 and lo <= lu[i] <= hi)

    # فتحةٌ تُذكر لا لمعةٌ أو حجرٌ صغير على القطعة
    min_hole = max(24, int(n * 0.005))
    seen = bytearray(n)
    for s0 in range(n):
        if rem[s0] or seen[s0] or not _holeish(s0):
            continue
        comp = [s0]
        seen[s0] = 1
        k = 0
        while k < len(comp):
            i = comp[k]
            k += 1
            x = i % w
            for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1,
                      i - w, i + w):
                if 0 <= j < n and not rem[j] and not seen[j] \
                        and _holeish(j):
                    seen[j] = 1
                    comp.append(j)
        if len(comp) >= min_hole:
            for i in comp:
                rem[i] = 1

    # ══ بقايا لون الخلفية على حافّة القطعة (هالة) ══
    halo = (tol * 1.4) ** 2
    edge = []
    for i in range(n):
        if rem[i] or dbg[i] > halo or abs(ch[i] - bc) > 22:
            continue
        x = i % w
        if (x and rem[i - 1]) or (x < w - 1 and rem[i + 1]) \
                or (i >= w and rem[i - w]) or (i < n - w and rem[i + w]):
            edge.append(i)
    for i in edge:
        rem[i] = 1

    keep = bytearray(0 if r else 255 for r in rem)
    kept = n - sum(rem)
    if kept < n * 0.01:
        raise CutoutError("لم يبقَ من الصورة شيءٌ يُذكر بعد إزالة الخلفية"
                          " — القطعة بلون الخلفية نفسه، فتُركت كما هي")
    if kept > n * 0.985:
        raise CutoutError("لم تُوجد خلفيةٌ تُزال حول القطعة — تُركت كما هي")
    tone = ("سوداء" if br + bg + bb < 150 else
            "بيضاء" if br + bg + bb > 600 else "ملوّنة")
    return keep, w, h, f"أُزيلت خلفيةٌ {tone}", (br, bg, bb), tol


_BAND = re.compile(rb"[\x01-\xfe]+")


def _refine_edges(img, alpha, bgc, tol):
    """حافّة القطعة بدقّة الصورة الكاملة: شفافيةٌ متدرّجة بحسب اللون،
    ولونٌ مُنقّى من خلفيته (فلا هالة سوداء حول الذهب على ورقٍ أبيض).

    `alpha`: القناع مكبَّراً بنعومة (Grayscale8) — يُعدَّل في مكانه
    على شريط الحافّة وحده (ما بين الشفاف تماماً والمعتم تماماً).
    """
    W, H = img.width(), img.height()
    if alpha.format() != QtGui.QImage.Format_Grayscale8:
        alpha = alpha.convertToFormat(QtGui.QImage.Format_Grayscale8)
    if img.format() != QtGui.QImage.Format_ARGB32:
        img = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    ast = alpha.bytesPerLine()
    a_buf = bytearray(_bytes(alpha))
    ist = img.bytesPerLine()
    px = bytearray(_bytes(img))
    br, bg, bb = bgc
    lo, hi = tol * 0.55, tol * 2.0
    span = hi - lo
    for y in range(H):
        row0 = y * ast
        for m in _BAND.finditer(a_buf, row0, row0 + W):
            for k in range(m.start(), m.end()):
                mv = a_buf[k]
                x = k - row0
                o = y * ist + x * 4
                b, g, r = px[o], px[o + 1], px[o + 2]
                d = ((r - br) ** 2 + (g - bg) ** 2 + (b - bb) ** 2) ** 0.5
                ac = 0.0 if d <= lo else 1.0 if d >= hi else (d - lo) / span
                a = ac * 255.0
                a = max(a, (mv - 128) * 2.0)      # داخل القطعة يبقى معتماً
                a = min(a, mv * 2.0)              # وخارجها يبقى شفافاً
                a_buf[k] = int(a)
                if 38 <= a < 255:
                    f = a / 255.0
                    inv = 1.0 - f
                    px[o] = max(0, min(255, int((b - inv * bb) / f)))
                    px[o + 1] = max(0, min(255, int((g - inv * bg) / f)))
                    px[o + 2] = max(0, min(255, int((r - inv * br) / f)))
    out = QtGui.QImage(bytes(px), W, H, ist,
                       QtGui.QImage.Format_ARGB32).copy()
    am = QtGui.QImage(bytes(a_buf), W, H, ast,
                      QtGui.QImage.Format_Grayscale8).copy()
    return out, am


def _bbox(keep, w, h):
    xs0, ys0, xs1, ys1 = w, h, -1, -1
    for y in range(h):
        row = keep[y * w:(y + 1) * w]
        if 255 not in row:
            continue
        ys0 = min(ys0, y)
        ys1 = y
        a = row.index(255)
        b = w - 1 - row[::-1].index(255)
        xs0, xs1 = min(xs0, a), max(xs1, b)
    if xs1 < 0:
        return None
    return xs0, ys0, xs1, ys1


def cutout(img):
    """الصورة بلا خلفية ومقصوصةً على القطعة — (QImage، وصف)."""
    if img.isNull():
        raise CutoutError("تعذّرت قراءة الصورة")
    if max(img.width(), img.height()) > MAX_SIDE:
        img = img.scaled(MAX_SIDE, MAX_SIDE, QtCore.Qt.KeepAspectRatio,
                         QtCore.Qt.SmoothTransformation)
    keep, w, h, note, bgc, tol = mask_of(img)
    W, H = img.width(), img.height()
    m = QtGui.QImage(bytes(keep), w, h, w, QtGui.QImage.Format_Grayscale8)
    m = m.copy()                         # يملك بياناته
    # تكبير القناع بنعومة، ثم تُحسب الحافّة بدقّة الصورة الكاملة
    # (التكبير الناعم يعيد صورةً 32 بت — فتُعاد رماديةً صراحةً)
    m = m.scaled(W, H, QtCore.Qt.IgnoreAspectRatio,
                 QtCore.Qt.SmoothTransformation).convertToFormat(
        QtGui.QImage.Format_Grayscale8)
    out = img.convertToFormat(QtGui.QImage.Format_ARGB32)
    if bgc is not None:
        out, m = _refine_edges(out, m, bgc, tol)
    out.setAlphaChannel(m)
    box = _bbox(keep, w, h)
    if box:
        sx, sy = W / float(w), H / float(h)
        x0, y0 = box[0] * sx, box[1] * sy
        x1, y1 = (box[2] + 1) * sx, (box[3] + 1) * sy
        pad = MARGIN * max(x1 - x0, y1 - y0)
        r = QtCore.QRect(int(max(0, x0 - pad)), int(max(0, y0 - pad)),
                         int(min(W, x1 + pad) - max(0, x0 - pad)),
                         int(min(H, y1 + pad) - max(0, y0 - pad)))
        out = out.copy(r)
    return out, note


def cutout_file(src, dst):
    """يقرأ صورةً ويكتبها بلا خلفية PNG — ويعيد الوصف."""
    r = QtGui.QImageReader(str(src))
    r.setAutoTransform(True)             # اتجاه صورة الجوال كما التُقطت
    img = r.read()
    if img.isNull():
        raise CutoutError("تعذّرت قراءة الصورة: " + (r.errorString() or ""))
    out, note = cutout(img)
    if not out.save(str(dst), "PNG"):
        raise CutoutError("تعذّر حفظ الصورة بعد إزالة الخلفية")
    return note


def flatten(img, color="#FFFFFF"):
    """صورةٌ شفافة على لونٍ واحد — قبل حفظها JPEG (لا شفافية فيه).

    بدونها تخرج الأجزاء الشفافة **سوداء** في كل صورةٍ مصغّرة JPEG.
    """
    if not img.hasAlphaChannel():
        return img
    out = QtGui.QImage(img.size(), QtGui.QImage.Format_RGB32)
    out.fill(QtGui.QColor(color))
    p = QtGui.QPainter(out)
    p.drawImage(0, 0, img)
    p.end()
    return out
