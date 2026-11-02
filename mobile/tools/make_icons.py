"""أيقونات ÀUR من الشعار الأصلي (mobile/store/aur-logo.jpg) لكل مكان:

    python3 mobile/tools/make_icons.py

- أندرويد: أيقونةٌ تكيّفية (8+): خلفيةٌ سوداء من الشعار نفسه، والشعار الذهبي في
  المنطقة الآمنة فيبقى كاملاً في كل شكل (دائرة · مربّع مستدير)؛ وأيقونةٌ عادية
  ومستديرة للأجهزة الأقدم.
- الواجهة: web/img/icon.png (الشريط وشاشة الترحيب).
- المتاجر: Google Play 512 · App Store 1024 (مربّعةٌ بلا شفافية — المتجر يدوّرها)،
  وصورة Play المميّزة 1024×500، وأيقونات iOS.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

M = Path(__file__).resolve().parent.parent
SRC = Image.open(M / "store" / "aur-logo.jpg").convert("RGB")
N = SRC.size[0]
RES = M / "android" / "app" / "src" / "main" / "res"
DENS = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
BLACK = tuple(int(v) for v in np.asarray(SRC)[N // 2 + 300, N // 2])   # سواد الشعار نفسه


def rounded(im, r):
    """البلاطة بزواياها المستديرة وما خارجها شفاف."""
    m = Image.new("L", (im.size[0] * 4, im.size[1] * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, m.size[0] - 1, m.size[1] - 1], radius=r * 4, fill=255)
    out = im.convert("RGBA")
    out.putalpha(m.resize(im.size, Image.LANCZOS))
    return out


def circle(im):
    m = Image.new("L", (im.size[0] * 4, im.size[1] * 4), 0)
    ImageDraw.Draw(m).ellipse([0, 0, m.size[0] - 1, m.size[1] - 1], fill=255)
    out = im.convert("RGBA")
    out.putalpha(m.resize(im.size, Image.LANCZOS))
    return out


def emblem():
    """الشعار الذهبي وحده (الماسة والحروف والقوس) بشفافيةٍ من إضاءته — بلا إطار
    البلاطة ولا موجتي الزاويتين، ليوضع على خلفيةٍ سوداء في أي شكل."""
    a = np.asarray(SRC).astype(np.float32)
    L = a.mean(axis=2)
    alpha = np.clip((L - 40) / 60, 0, 1)                # السواد وظلال الإطار الرمادية شفافة
    yy, xx = np.mgrid[0:N, 0:N] / N
    keep = np.ones_like(L)
    keep[(xx < 0.085) | (xx > 0.915) | (yy < 0.17) | (yy > 0.775)] = 0
    keep[yy < 0.27 - 0.6 * xx] = 0                    # موجة الزاوية العليا
    keep[yy > 1.66 - 0.75 * xx] = 0                   # موجة الزاوية السفلى
    keep[(xx < 0.13) & (yy < 0.6)] = 0               # بريق حافّة البلاطة يساراً
    keep[(xx > 0.85) & (yy > 0.66)] = 0               # ويميناً أسفل
    keep[(xx < 0.36) & (yy < 0.27)] = 0               # (قبل الماسة: لا شيء من الشعار)
    keep[(xx > 0.70) & (yy > 0.70)] = 0
    rgba = np.dstack([a, alpha * keep * 255]).astype(np.uint8)
    im = Image.fromarray(rgba, "RGBA")
    return im.crop(im.getbbox())


def save(im, path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    im.resize((size, size), Image.LANCZOS).save(path, optimize=True)


def main():
    em = emblem()
    tile = SRC                                        # الشعار كاملاً (مربّع، زواياه سوداء)
    # ── أندرويد: العادية (زوايا مستديرة) والمستديرة، لكل كثافة ──
    for d, k in DENS.items():
        save(rounded(tile, int(N * 0.18)), RES / f"mipmap-{d}" / "ic_launcher.png", int(48 * k))
        save(circle(tile), RES / f"mipmap-{d}" / "ic_launcher_round.png", int(48 * k))
        # التكيّفية: طبقة أمامية 108dp — الشعار في 64% من عرضها (داخل الدائرة الآمنة)
        side = int(108 * k)
        fg = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        w = int(side * 0.64)
        h = int(em.size[1] * w / em.size[0])
        fg.alpha_composite(em.resize((w, h), Image.LANCZOS), ((side - w) // 2, (side - h) // 2 + int(side * 0.01)))
        save(fg, RES / f"mipmap-{d}" / "ic_launcher_foreground.png", side)
    any_dir = RES / "mipmap-anydpi-v26"
    any_dir.mkdir(exist_ok=True)
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n'
           '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
           '    <background android:drawable="@color/icon_bg" />\n'
           '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
           '    <monochrome android:drawable="@mipmap/ic_launcher_foreground" />\n'
           '</adaptive-icon>\n')
    (any_dir / "ic_launcher.xml").write_text(xml, encoding="utf-8")
    (any_dir / "ic_launcher_round.xml").write_text(xml, encoding="utf-8")
    (RES / "values" / "icon_bg.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <!-- سواد شعار ÀUR نفسه (خلفية الأيقونة التكيّفية) -->\n'
        f'    <color name="icon_bg">#{BLACK[0]:02X}{BLACK[1]:02X}{BLACK[2]:02X}</color>\n</resources>\n',
        encoding="utf-8")
    # ── الواجهة ──
    save(rounded(tile, int(N * 0.18)), M / "web" / "img" / "icon.png", 288)
    # ── المتاجر ──
    store = M / "store"
    save(tile, store / "google-play-icon-512.png", 512)
    save(tile, store / "app-store-icon-1024.png", 1024)
    fg = Image.new("RGB", (1024, 500), BLACK)
    big = em.resize((int(em.size[0] * 330 / em.size[1]), 330), Image.LANCZOS)
    fg.paste(big, ((1024 - big.size[0]) // 2, (500 - 330) // 2), big)
    store.mkdir(exist_ok=True)
    fg.save(store / "google-play-feature-1024x500.png", optimize=True)
    # ── iOS: أيقونة واحدة 1024 (Xcode 14+ يولّد الباقي) ──
    ios = M / "ios" / "AUR" / "Assets.xcassets" / "AppIcon.appiconset"
    ios.mkdir(parents=True, exist_ok=True)
    tile.resize((1024, 1024), Image.LANCZOS).save(ios / "icon-1024.png", optimize=True)
    (ios / "Contents.json").write_text(json.dumps({
        "images": [{"filename": "icon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}],
        "info": {"author": "xcode", "version": 1}}, indent=2), encoding="utf-8")
    (ios.parent / "Contents.json").write_text(json.dumps({"info": {"author": "xcode", "version": 1}}, indent=2),
                                             encoding="utf-8")
    print("✔ icons", BLACK)


if __name__ == "__main__":
    main()
