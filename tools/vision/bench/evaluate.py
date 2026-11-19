# -*- coding: utf-8 -*-
"""تقييم نماذج «البحث بالصورة» على مجموعة الأطقم (make_sets.py).

لكل لقطةٍ «كالجوال»: ترتيب الطقم الصحيح بين كل صور الكتالوج.
يقارن النماذج، وطريقة تجهيز الصورة (حشوٌ مربّع أم قصّ)، وتجميع الرموز
(CLS · متوسط · GeM · كلاهما)، وزوايا الكتالوج (القطع منفصلة · نوافذ)،
وتنويعات الصورة المصوَّرة (قصٌّ أضيق · مرآة).

    python evaluate.py <مجلد-المجموعة> <مجلد-النماذج> [نموذج…]
"""
import io
import json
import math
import random
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageFilter

BENCH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("bench")
MODELS = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("vm")
ONLY = sys.argv[3:]

IMNET = ((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))
CLIPN = ((0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711))
HALF = ((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))

# الاسم: (الملف، المقاس، التطبيع، نوع المخرج)
CANDIDATES = {
    "dinov2-s": ("Xenova__dinov2-small__onnx__model.onnx", 224, IMNET, "vit"),
    "dinov2-s-q8": ("Xenova__dinov2-small__onnx__model_quantized.onnx", 224, IMNET, "vit"),
    "dinov2-s@336": ("Xenova__dinov2-small__onnx__model.onnx", 336, IMNET, "vit"),
    "dinov2reg-s": ("onnx-community__dinov2-with-registers-small__onnx__model.onnx", 224, IMNET, "vit4"),
    "dinov2reg-s-q8": ("onnx-community__dinov2-with-registers-small__onnx__model_quantized.onnx", 224, IMNET, "vit4"),
    "dinov2-b-q8": ("Xenova__dinov2-base__onnx__model_quantized.onnx", 224, IMNET, "vit"),
    "dinov2reg-b-q8": ("onnx-community__dinov2-with-registers-base__onnx__model_quantized.onnx", 224, IMNET, "vit4"),
    "dinov3-s": ("onnx-community__dinov3-vits16-pretrain-lvd1689m-ONNX__onnx__model.onnx", 224, IMNET, "vit5"),
    "dinov3-s-q8": ("onnx-community__dinov3-vits16-pretrain-lvd1689m-ONNX__onnx__model_quantized.onnx", 224, IMNET, "vit5"),
    "dinov3-b-q8": ("onnx-community__dinov3-vitb16-pretrain-lvd1689m-ONNX__onnx__model_quantized.onnx", 224, IMNET, "vit5"),
    "clip-b32-q8": ("Xenova__clip-vit-base-patch32__onnx__vision_model_quantized.onnx", 224, CLIPN, "embeds"),
    "clip-b16-q8": ("Xenova__clip-vit-base-patch16__onnx__vision_model_quantized.onnx", 224, CLIPN, "embeds"),
    "siglip-b-q8": ("Xenova__siglip-base-patch16-224__onnx__vision_model_quantized.onnx", 224, HALF, "pooler"),
    "mobileclip-s0": ("Xenova__mobileclip_s0__onnx__vision_model.onnx", 256, ((0, 0, 0), (1, 1, 1)), "embeds"),
    "mobileclip-s2-q8": ("Xenova__mobileclip_s2__onnx__vision_model_quantized.onnx", 256, ((0, 0, 0), (1, 1, 1)), "embeds"),
}


# ── «تصوير الجوال»: ضجيجٌ وضغطٌ وميلانٌ لوني وقصٌّ غير متقن ──
def phoneify(path, seed):
    rng = random.Random(seed)
    im = Image.open(path).convert("RGB")
    w, h = im.size
    l, t = rng.uniform(0, .08) * w, rng.uniform(0, .08) * h
    r, b = w - rng.uniform(0, .08) * w, h - rng.uniform(0, .08) * h
    im = im.crop((int(l), int(t), int(r), int(b)))
    a = np.asarray(im).astype(np.float32)
    a *= np.array([rng.uniform(.93, 1.07), rng.uniform(.95, 1.05), rng.uniform(.88, 1.04)])
    a += np.random.default_rng(seed).normal(0, rng.uniform(1.5, 6), a.shape)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if rng.random() < .6:
        im = im.filter(ImageFilter.GaussianBlur(rng.uniform(.3, 1.1)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=rng.randint(55, 85))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def catalog_image(path):
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
    bg.alpha_composite(im)
    im = bg.convert("RGB")
    buf = io.BytesIO()                          # كما يرسلها الرابط: JPEG
    im.save(buf, "JPEG", quality=84)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


# ── المساقط ──
def fg_mask(im):
    """ما ليس خلفيةً: لون الخلفية من الحوافّ (كالمطبَّق في الصفحة)."""
    a = np.asarray(im).astype(np.int16)
    edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bgc = np.median(edge, axis=0)
    d = np.abs(a - bgc).max(axis=2)
    return (d > 28).astype(np.uint8)


def bbox_of(m):
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def pad_square(im, box=None, fill=None, margin=0.06):
    if box is not None:
        im = im.crop(box)
    w, h = im.size
    s = int(max(w, h) * (1 + margin))
    if fill is None:
        a = np.asarray(im)
        edge = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
        fill = tuple(int(x) for x in np.median(edge, axis=0))
    out = Image.new("RGB", (s, s), fill)
    out.paste(im, ((s - w) // 2, (s - h) // 2))
    return out


def center_square(im, frac=1.0):
    w, h = im.size
    s = int(min(w, h) * frac)
    l, t = (w - s) // 2, (h - s) // 2
    return im.crop((l, t, l + s, t + s))


def catalog_views(im, kind):
    """زوايا الكتالوج: الكل · القطع منفصلة · نوافذ."""
    views = []
    m = fg_mask(im)
    box = bbox_of(m)
    views.append(pad_square(im, box, (255, 255, 255)))
    if kind in ("pieces", "pieces+win", "all"):
        k = cv2.dilate(m, np.ones((7, 7), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(k, 8)
        tot = m.sum()
        comps = [i for i in range(1, n) if m[lab == i].sum() > 0.025 * tot]
        if len(comps) > 1:
            for i in sorted(comps, key=lambda i: -st[i, cv2.CC_STAT_AREA])[:5]:
                x, y, w, h = st[i, :4]
                views.append(pad_square(im, (x, y, x + w, y + h), (255, 255, 255), 0.15))
    if kind in ("win", "pieces+win", "all") and box:
        x0, y0, x1, y1 = box
        W, H = x1 - x0, y1 - y0
        for fx, fy in ((0, 0), (1, 0), (0, 1), (1, 1), (.5, .5)):
            cw, ch = W * .55, H * .55
            cx, cy = x0 + fx * (W - cw), y0 + fy * (H - ch)
            sub = (int(cx), int(cy), int(cx + cw), int(cy + ch))
            if fg_mask(im.crop(sub)).mean() > 0.01:
                views.append(pad_square(im, sub, (255, 255, 255), 0.05))
    if kind == "all":
        dark = Image.new("RGB", im.size, (24, 22, 26))
        dark.paste(im, (0, 0), Image.fromarray((fg_mask(im) * 255).astype(np.uint8)))
        views.append(pad_square(dark, box, (24, 22, 26)))
    return views


def query_views(im, kind):
    sq = center_square(im, 1.0)
    out = [sq]
    if kind in ("crops", "crops+flip"):
        out += [center_square(im, .8), center_square(im, .62)]
    if kind in ("flip", "crops+flip"):
        out.append(sq.transpose(Image.FLIP_LEFT_RIGHT))
    return out


# ── النموذج ──
class Enc:
    def __init__(self, name):
        f, self.size, (mean, std), self.kind = CANDIDATES[name]
        so = ort.SessionOptions()
        so.intra_op_num_threads = 4
        self.s = ort.InferenceSession(str(MODELS / f), so, providers=["CPUExecutionProvider"])
        self.inp = self.s.get_inputs()[0].name
        self.outs = [o.name for o in self.s.get_outputs()]
        self.mean = np.array(mean, np.float32)[:, None, None]
        self.std = np.array(std, np.float32)[:, None, None]

    def prep(self, im):
        im = im.resize((self.size, self.size), Image.BICUBIC)
        a = np.asarray(im, np.float32).transpose(2, 0, 1) / 255.0
        return (a - self.mean) / self.std

    def run(self, ims, bs=16):
        res = {}
        for i in range(0, len(ims), bs):
            x = np.stack([self.prep(im) for im in ims[i:i + bs]])
            out = dict(zip(self.outs, self.s.run(None, {self.inp: x})))
            for k, v in self.feats(out).items():
                res.setdefault(k, []).append(v)
        return {k: np.concatenate(v) for k, v in res.items()}

    def feats(self, out):
        if self.kind == "embeds":
            e = out.get("image_embeds")
            if e is None:
                e = list(out.values())[0]
            return {"emb": e.reshape(len(e), -1)}
        if self.kind == "pooler":
            return {"emb": out["pooler_output"]}
        h = out["last_hidden_state"]
        skip = {"vit": 1, "vit4": 5, "vit5": 5}[self.kind]
        cls, pat = h[:, 0], h[:, skip:]
        p = np.clip(pat, 1e-6, None)
        gem = np.mean(p ** 3, axis=1) ** (1 / 3)
        po = out.get("pooler_output")
        return {"cls": po if po is not None else cls, "mean": pat.mean(1), "gem": gem,
                "cls+mean": np.concatenate([norm(po if po is not None else cls),
                                            norm(pat.mean(1))], 1)}


def norm(x):
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9)


def ranks(qf, qid, cf, cid, agg):
    """ترتيب الصحيح لكل لقطة. qf: [لقطة][تنويع] · cf: [طقم][زاوية]."""
    out = []
    for q, true in zip(qf, qid):
        sc = []
        for c in cf:
            s = q @ c.T                         # تنويعات × زوايا
            if agg == "max":
                sc.append(s.max())
            else:                               # لكل تنويعٍ أفضل زاوية، ثم المتوسط
                sc.append(s.max(1).mean())
        order = np.argsort(-np.array(sc))
        out.append(int(np.nonzero(np.array(cid)[order] == true)[0][0]) + 1)
    return np.array(out)


def summary(r):
    return (f"top1 {np.mean(r == 1) * 100:5.1f}  top5 {np.mean(r <= 5) * 100:5.1f}"
            f"  top10 {np.mean(r <= 10) * 100:5.1f}  mrr {np.mean(1 / r):.3f}")


def main():
    meta = json.loads((BENCH / "meta.json").read_text(encoding="utf-8"))
    cats = {m["id"]: catalog_image(BENCH / "catalog" / f"{m['id']}.png") for m in meta}
    shots = []
    for m in meta:
        for k, s in enumerate(m["shots"]):
            seed = hash((m["id"], k)) & 0xFFFF
            shots.append((m["id"], s["kind"], phoneify(BENCH / "raw" / s["file"], seed)))
    ids = list(cats)
    print(f"{len(ids)} طقماً · {len(shots)} لقطة "
          f"({sum(1 for s in shots if s[1] == 'set')} للطقم كاملاً)")
    names = ONLY or list(CANDIDATES)
    configs = [("full", "single"), ("pieces", "single"), ("pieces+win", "single"),
               ("pieces+win", "crops"), ("pieces+win", "crops+flip"), ("all", "crops+flip")]
    results = {}
    for name in names:
        if not (MODELS / CANDIDATES[name][0]).exists():
            print(f"── {name}: غير موجود")
            continue
        try:
            enc = Enc(name)
        except Exception as e:
            print(f"── {name}: {e}")
            continue
        t0 = time.time()
        cache_c, cache_q = {}, {}
        for ck, qk in configs:
            if ck not in cache_c:
                vs = {i: catalog_views(cats[i], ck) for i in ids}
                flat = [v for i in ids for v in vs[i]]
                f = enc.run(flat)
                cache_c[ck] = (vs, f)
            if qk not in cache_q:
                qv = [query_views(s[2], qk) for s in shots]
                f = enc.run([v for vv in qv for v in vv])
                cache_q[qk] = (qv, f)
        dt = time.time() - t0
        for ck, qk in configs:
            vs, cfe = cache_c[ck]
            qv, qfe = cache_q[qk]
            for feat in cfe:
                cf, pos = [], 0
                for i in ids:
                    n = len(vs[i])
                    cf.append(norm(cfe[feat][pos:pos + n]))
                    pos += n
                qf, pos = [], 0
                for vv in qv:
                    qf.append(norm(qfe[feat][pos:pos + len(vv)]))
                    pos += len(vv)
                for agg in ("max", "meanmax"):
                    if qk == "single" and agg == "meanmax":
                        continue
                    r = ranks(qf, [s[0] for s in shots], cf, ids, agg)
                    rs = r[[s[1] == "set" for s in shots]]
                    rp = r[[s[1] != "set" for s in shots]]
                    key = f"{name:16s} {feat:8s} cat={ck:10s} q={qk:10s} {agg:7s}"
                    results[key] = (np.mean(1 / r), summary(r), summary(rs), summary(rp))
        print(f"── {name}  ({dt:.0f} ث)")
        for key, (_, a, s_, p_) in sorted(
                ((k, v) for k, v in results.items() if k.startswith(f"{name:16s}")),
                key=lambda kv: -kv[1][0])[:6]:
            print(f"  {key}\n     الكل  {a}\n     طقم   {s_}\n     قطعة  {p_}")
    print("\n══ الأفضل ══")
    for key, (_, a, s_, p_) in sorted(results.items(), key=lambda kv: -kv[1][0])[:15]:
        print(f"  {key}  | {a} | طقم {s_.split('  mrr')[0]} | قطعة {p_.split('  mrr')[0]}")
    (BENCH / "results.json").write_text(json.dumps(
        {k: list(v) for k, v in results.items()}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
