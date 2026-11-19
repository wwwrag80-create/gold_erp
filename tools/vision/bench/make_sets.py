# -*- coding: utf-8 -*-
"""مجموعة اختبارٍ لـ«البحث بالصورة»: أطقم ذهبٍ إجرائية بـBlender (حزمة bpy).

لكل تصميم: صورة «كتالوج» (رسمٌ ثلاثي الأبعاد نظيف على أبيض — كصور الدليل)
وعدّة «لقطات» تحاكي تصوير الجوال: زاويةٌ مائلة، قماشٌ مخملي، إضاءةٌ دافئة
غير منتظمة، ذهبٌ أخشن قليلاً، عمق ميدان — ولقطةٌ لقطعةٍ واحدة من الطقم.
والتصاميم عائلاتٌ متقاربة (نفس الفكرة بتغييرٍ واحد) فيصعب التمييز كما في
مصنعٍ حقيقي.

    python make_sets.py <مجلد> <عدد العائلات> [بذرة]

أداة تطوير لا يحتاجها البرنامج.
"""
import json
import math
import random
import sys
from pathlib import Path

import bpy  # noqa: I001 — قبل bmesh: حزمة bpy تضيف مسار وحداتها
import bmesh
from mathutils import Euler, Vector

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "bench")
FAMILIES = int(sys.argv[2]) if len(sys.argv) > 2 else 20
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 7
VARIANTS = 3
CAT_RES, PHO_RES = 384, 448


# ── أشكالٌ ثنائية الأبعاد (تُبثق) ──
def poly_circle(n=24, r=1.0):
    return [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def poly_star(k=5, r1=1.0, r2=0.45):
    pts = []
    for i in range(2 * k):
        r = r1 if i % 2 == 0 else r2
        a = math.pi / 2 + math.pi * i / k
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def poly_heart(n=40):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((x / 17, y / 17))
    return pts


def poly_leaf(n=28, w=0.42):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        pts.append((w * math.sin(t) * abs(math.sin(t)) ** 0.1, math.cos(t)))
    return pts


def poly_drop(n=32):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = math.sin(t) * (1 - math.cos(t)) * 0.5
        y = -math.cos(t)
        pts.append((x * 1.1, y))
    return pts


def poly_square(r=1.0):
    return [(r, 0), (0, r), (-r, 0), (0, -r)]


def poly_hex(r=1.0):
    return poly_circle(6, r)


def poly_flower(k=6, r=1.0, depth=0.35, n=72):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        rr = r * (1 - depth + depth * abs(math.cos(k * t / 2)))
        pts.append((rr * math.cos(t), rr * math.sin(t)))
    return pts


SHAPES = {
    "circle": lambda: poly_circle(28),
    "star5": lambda: poly_star(5),
    "star6": lambda: poly_star(6, 1, 0.55),
    "heart": poly_heart,
    "leaf": poly_leaf,
    "drop": poly_drop,
    "square": poly_square,
    "hex": poly_hex,
    "flower5": lambda: poly_flower(5),
    "flower6": lambda: poly_flower(6),
    "flower8": lambda: poly_flower(8, 1, 0.25),
}


def extrude_mesh(name, pts, depth=0.25, dome=0.0):
    """شكلٌ مبثوق بسماكة — ووجهٌ علوي مقبّب قليلاً إن طُلب."""
    bm = bmesh.new()
    top = [bm.verts.new((x, y, depth / 2)) for x, y in pts]
    bot = [bm.verts.new((x, y, -depth / 2)) for x, y in pts]
    n = len(pts)
    bm.faces.new(bot[::-1])
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((bot[i], bot[j], top[j], top[i]))
    if dome > 0:
        c = bm.verts.new((sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n,
                          depth / 2 + dome))
        for i in range(n):
            bm.faces.new((top[i], top[(i + 1) % n], c))
    else:
        bm.faces.new(top)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    return me


def tube_mesh(name, path, r=0.06, closed=False, seg=10):
    """أنبوبٌ دائري المقطع على مسارٍ ثلاثي الأبعاد (سلسلة · طوق · إطار)."""
    bm = bmesh.new()
    rings = []
    m = len(path)
    for i, p in enumerate(path):
        p = Vector(p)
        a = Vector(path[(i - 1) % m] if (closed or i > 0) else path[i])
        b = Vector(path[(i + 1) % m] if (closed or i < m - 1) else path[i])
        t = (b - a).normalized() if (b - a).length > 1e-9 else Vector((1, 0, 0))
        up = Vector((0, 0, 1)) if abs(t.z) < 0.9 else Vector((1, 0, 0))
        nrm = t.cross(up).normalized()
        bin_ = t.cross(nrm).normalized()
        ring = []
        for k in range(seg):
            ang = 2 * math.pi * k / seg
            ring.append(bm.verts.new(p + r * (math.cos(ang) * nrm + math.sin(ang) * bin_)))
        rings.append(ring)
    last = m if closed else m - 1
    for i in range(last):
        r0, r1 = rings[i], rings[(i + 1) % m]
        for k in range(seg):
            bm.faces.new((r0[k], r0[(k + 1) % seg], r1[(k + 1) % seg], r1[k]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    return me


def sphere_mesh(name, r=1.0):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=20, v_segments=14, radius=r)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    return me


def torus_path(R, n=40):
    return [(R * math.cos(2 * math.pi * i / n), R * math.sin(2 * math.pi * i / n), 0)
            for i in range(n)]


# ── المواد ──
def gold_mat(rough=0.12, tint=(1.0, 0.72, 0.30)):
    m = bpy.data.materials.get("gold") or bpy.data.materials.new("gold")
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*tint, 1)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = rough
    return m


def gem_mat(name, color):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = 0.02
    b.inputs["IOR"].default_value = 2.1
    b.inputs["Transmission Weight"].default_value = 0.95
    return m


def velvet_mat(color):
    m = bpy.data.materials.new("velvet")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = 0.92
    b.inputs["Sheen Weight"].default_value = 0.8
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 180.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


# ── التصميم ──
def new_design(rng):
    """وصف طقمٍ عشوائي: عقدٌ بعناصر متكررة · قلادة · حلق · خاتم."""
    names = list(SHAPES)
    return {
        "beadA": rng.choice(names),
        "beadB": rng.choice(names + ["sphere", "none"]),
        "count": rng.randint(9, 23),
        "grad": rng.uniform(0.0, 0.8),          # تدرّج الحجم نحو الوسط
        "bsize": rng.uniform(0.32, 0.6),
        "dome": rng.choice([0.0, 0.0, 0.15, 0.3]),
        "chain": rng.choice([0.05, 0.07, 0.1]),
        "pend": rng.choice(names),
        "pend_size": rng.uniform(1.3, 2.4),
        "pend_gem": rng.choice([None, None, (0.95, 0.95, 0.97), (0.8, 0.05, 0.08),
                                (0.05, 0.6, 0.15), (0.1, 0.25, 0.9)]),
        "pend_frame": rng.random() < 0.45,
        "pend_drop": rng.choice([None, "drop", "leaf", "circle", "heart"]),
        "bead_gem": rng.random() < 0.3,
        "earrings": rng.random() < 0.85,
        "ring": rng.random() < 0.6,
        "bracelet": rng.random() < 0.25,
        "arc": rng.uniform(95, 130),
        "rot": rng.choice([0.0, 0.0, math.pi / 4, math.pi]),
    }


def mutate(d, rng, siblings=()):
    """أخٌ متقارب في العائلة: يُغيَّر شيءٌ واحد أو اثنان — ظاهران."""
    base = d
    for _ in range(50):
        d = dict(base)
        keys = ["beadA", "beadB", "count", "pend", "pend_drop", "pend_gem",
                "pend_frame", "bsize"]
        for k in rng.sample(keys, rng.choice([1, 1, 2])):
            if k in ("beadA", "pend"):
                d[k] = rng.choice([s for s in SHAPES if s != d[k]])
            elif k == "beadB":
                d[k] = rng.choice([s for s in list(SHAPES) + ["sphere", "none"]
                                   if s != d[k]])
            elif k == "count":
                d[k] = max(7, d[k] + rng.choice([-6, -4, 4, 6]))
            elif k == "pend_drop":
                d[k] = rng.choice([x for x in [None, "drop", "leaf", "circle", "heart"]
                                   if x != d[k]])
            elif k == "pend_gem":
                d[k] = rng.choice([x for x in [None, (0.95, 0.95, 0.97),
                                               (0.8, 0.05, 0.08), (0.05, 0.6, 0.15)]
                                   if x != d[k]])
            elif k == "pend_frame":
                d[k] = not d[k]
            elif k == "bsize":
                d[k] = min(0.7, max(0.28, d[k] * rng.choice([0.7, 1.4])))
        if d != base and all(d != s for s in siblings):
            return d
    return d


def place(me, mat, loc, rot_z=0.0, scale=1.0, tilt=None, name="o"):
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = tilt if tilt is not None else Euler((0, 0, rot_z))
    ob.scale = (scale, scale, scale)
    ob.data.materials.clear() if False else None
    if not me.materials:
        me.materials.append(mat)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def motif(kind, cache, gold, depth=0.25, dome=0.0):
    key = (kind, round(depth, 3), round(dome, 3))
    if key not in cache:
        if kind == "sphere":
            me = sphere_mesh("sph")
        else:
            me = extrude_mesh(kind, SHAPES[kind](), depth, dome)
        me.materials.append(gold)
        cache[key] = me
    return cache[key]


def build(d, gold):
    """يبني الطقم في المشهد — ويعيد مراكز القطع (للقطات القطعة الواحدة)."""
    cache, pieces = {}, {}
    gems = {}

    def gem(color):
        k = tuple(color)
        if k not in gems:
            gems[k] = gem_mat("gem", color)
        return gems[k]

    gem_me = sphere_mesh("gem")

    def put_gem(loc, r, color):
        me = gem_me.copy()
        me.materials.clear()
        me.materials.append(gem(color))
        place(me, None, loc, scale=r)

    # العقد: قوسٌ بيضاوي مفتوح من الأعلى
    rx, ry, cy = 6.0, 7.0, 4.0
    amax = math.radians(d["arc"])
    path = []
    for i in range(121):
        a = -amax + 2 * amax * i / 120
        path.append((rx * math.sin(a), cy - ry * math.cos(a), 0))
    chain = tube_mesh("chain", path, d["chain"])
    chain.materials.append(gold)
    place(chain, gold, (0, 0, 0))
    n = d["count"]
    for i in range(n):
        a = -amax * 0.92 + 2 * amax * 0.92 * (i + 0.5) / n
        x, y = rx * math.sin(a), cy - ry * math.cos(a)
        center = 1 - abs(a) / amax
        s = d["bsize"] * (1 + d["grad"] * center)
        kind = d["beadA"] if (i % 2 == 0 or d["beadB"] == "none") else d["beadB"]
        me = motif(kind, cache, gold, 0.25, d["dome"])
        place(me, gold, (x, y, 0.12), rot_z=a + d["rot"],
              scale=s if kind != "sphere" else s * 0.55)
        if d["bead_gem"] and kind != "sphere" and i % 2 == 0:
            put_gem((x, y, 0.32), s * 0.28, (0.95, 0.95, 0.97))
    # القلادة
    py = cy - ry - 0.4 - d["pend_size"]
    pieces["pendant"] = (0.0, py, 0.0, d["pend_size"] * 1.6)
    bail = tube_mesh("bail", torus_path(0.28), 0.07, closed=True)
    bail.materials.append(gold)
    place(bail, gold, (0, cy - ry - 0.25, 0.1), tilt=Euler((math.pi / 2, 0, 0)))
    me = motif(d["pend"], cache, gold, 0.3, d["dome"])
    place(me, gold, (0, py, 0.15), rot_z=d["rot"], scale=d["pend_size"])
    if d["pend_frame"]:
        fr = tube_mesh("frame", [(x * 1.18, y * 1.18, 0) for x, y in SHAPES[d["pend"]]()],
                       0.06, closed=True)
        fr.materials.append(gold)
        place(fr, gold, (0, py, 0.15), rot_z=d["rot"], scale=d["pend_size"])
    if d["pend_gem"]:
        put_gem((0, py, 0.45), d["pend_size"] * 0.3, d["pend_gem"])
    if d["pend_drop"]:
        dy = py - d["pend_size"] * 1.25
        me = motif(d["pend_drop"], cache, gold, 0.22, d["dome"])
        place(me, gold, (0, dy, 0.12), scale=d["pend_size"] * 0.42)
        pieces["pendant"] = (0.0, (py + dy) / 2, 0.0, d["pend_size"] * 2.1)
    # الحلق: نسخةٌ صغيرة من القلادة بخطّاف
    if d["earrings"]:
        for sx in (-1, 1):
            ex, ey = sx * 8.8, -1.5
            hook = tube_mesh("hook", torus_path(0.3), 0.05, closed=True)
            hook.materials.append(gold)
            place(hook, gold, (ex, ey + 1.25, 0.1), tilt=Euler((math.pi / 2, 0, 0)))
            place(motif(d["pend"], cache, gold, 0.3, d["dome"]), gold,
                  (ex, ey, 0.15), rot_z=d["rot"], scale=d["pend_size"] * 0.5)
            if d["pend_gem"]:
                put_gem((ex, ey, 0.32), d["pend_size"] * 0.15, d["pend_gem"])
            if d["pend_drop"]:
                place(motif(d["pend_drop"], cache, gold, 0.22, d["dome"]), gold,
                      (ex, ey - d["pend_size"] * 0.62, 0.12), scale=d["pend_size"] * 0.22)
        pieces["earring"] = (8.8, -1.5 - d["pend_size"] * 0.25, 0.0, d["pend_size"] * 1.2)
    # الخاتم
    if d["ring"]:
        rx0, ry0 = 5.2 if d["earrings"] else 0.0, -7.6
        band = tube_mesh("band", torus_path(0.95, 48), 0.14, closed=True)
        band.materials.append(gold)
        place(band, gold, (rx0, ry0, 0.4), tilt=Euler((math.radians(62), 0, 0)))
        place(motif(d["beadA"], cache, gold, 0.25, d["dome"]), gold,
              (rx0, ry0 + 0.55, 1.15), rot_z=d["rot"], scale=0.7)
        pieces["ring"] = (rx0, ry0 + 0.2, 0.4, 1.7)
    # السوار
    if d["bracelet"]:
        bx, by = -5.6, -7.6
        br = tube_mesh("brc", torus_path(1.9, 64), 0.06, closed=True)
        br.materials.append(gold)
        place(br, gold, (bx, by, 0.05))
        for i in range(12):
            a = 2 * math.pi * i / 12
            place(motif(d["beadA"], cache, gold, 0.22, d["dome"]), gold,
                  (bx + 1.9 * math.cos(a), by + 1.9 * math.sin(a), 0.12),
                  rot_z=a, scale=d["bsize"] * 0.8)
        pieces["bracelet"] = (bx, by, 0.0, 4.6)
    return pieces


def bbox():
    bpy.context.view_layer.update()          # مصفوفات الأجسام الجديدة
    lo = Vector((1e9, 1e9, 1e9))
    hi = -lo
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH" or ob.name.startswith("floor"):
            continue
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def look_at(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def setup_render(res, samples):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 6
    sc.cycles.glossy_bounces = 4
    sc.cycles.transmission_bounces = 6
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = "Standard"


def area(name, loc, size, power, color=(1, 1, 1), target=(0, 0, 0)):
    li = bpy.data.lights.new(name, "AREA")
    li.size = size
    li.energy = power
    li.color = color
    ob = bpy.data.objects.new(name, li)
    ob.location = loc
    bpy.context.scene.collection.objects.link(ob)
    look_at(ob, target)
    return ob


def world(color, strength):
    w = bpy.data.worlds.new("w")
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*color, 1)
    bg.inputs["Strength"].default_value = strength
    bpy.context.scene.world = w


def render_to(path):
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def make_one(did, d, rng):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    gold = gold_mat()
    pieces = build(d, gold)
    lo, hi = bbox()
    c = (lo + hi) / 2
    span = max(hi.x - lo.x, hi.y - lo.y)
    sc = bpy.context.scene
    # ── الكتالوج: رسمٌ نظيف من الأعلى على شفاف (ثم أبيض) ──
    setup_render(CAT_RES, 24)
    sc.render.film_transparent = True
    world((1, 1, 1), 0.7)
    cam_d = bpy.data.cameras.new("cam")
    cam_d.type = "ORTHO"
    cam_d.ortho_scale = span * 1.08
    cam = bpy.data.objects.new("cam", cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.location = (c.x, c.y, 40)
    cam.rotation_euler = (0, 0, 0)
    lights = [area("k", (c.x - 8, c.y + 10, 18), 12, 2600, target=c),
              area("f", (c.x + 12, c.y - 4, 14), 14, 1500, target=c),
              area("t", (c.x, c.y, 25), 18, 1200, target=c)]
    render_to(OUT / "catalog" / f"{did}.png")
    for li in lights:
        bpy.data.objects.remove(li, do_unlink=True)
    # ── اللقطات: تحاكي جوالاً أمام طقمٍ حقيقي ──
    sc.render.film_transparent = False
    setup_render(PHO_RES, 40)
    bpy.data.meshes.new("floor")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=60)
    fme = bpy.data.meshes.new("floor")
    bm.to_mesh(fme)
    bm.free()
    floor = bpy.data.objects.new("floor", fme)
    floor.location = (c.x, c.y, -0.2)
    sc.collection.objects.link(floor)
    cam_d.type = "PERSP"
    cam_d.lens = 35
    shots = []
    kinds = ["set", "set", "piece"]
    for k, kind in enumerate(kinds):
        vel = rng.choice([(0.015, 0.015, 0.015), (0.09, 0.006, 0.012), (0.006, 0.012, 0.06),
                          (0.006, 0.04, 0.015), (0.42, 0.36, 0.28), (0.7, 0.7, 0.7),
                          (0.2, 0.12, 0.06)])
        fme.materials.clear()
        fme.materials.append(velvet_mat(vel))
        gm = gold_mat(rng.uniform(0.16, 0.34),
                      (1.0, rng.uniform(0.62, 0.78), rng.uniform(0.2, 0.36)))
        world((1.0, rng.uniform(0.75, 0.95), rng.uniform(0.55, 0.8)), rng.uniform(0.25, 0.7))
        if kind == "piece" and pieces:
            pname = rng.choice(sorted(pieces))
            px, py, pz, psize = pieces[pname]
            target = Vector((px, py, pz))
            dist = psize * rng.uniform(2.2, 3.0)
        else:
            pname = "set"
            target = c.copy()
            dist = span * rng.uniform(1.45, 1.75)
        tilt = math.radians(rng.uniform(8, 38))
        az = math.radians(rng.uniform(-30, 30)) - math.pi / 2
        cam.location = (target.x + dist * math.sin(tilt) * math.cos(az),
                        target.y + dist * math.sin(tilt) * math.sin(az),
                        target.z + dist * math.cos(tilt))
        look_at(cam, target + Vector((rng.uniform(-0.06, 0.06) * dist,
                                      rng.uniform(-0.06, 0.06) * dist, 0)))
        cam.rotation_euler.rotate(Euler((0, 0, math.radians(rng.uniform(-12, 12)))))
        cam_d.dof.use_dof = True
        cam_d.dof.focus_distance = dist
        cam_d.dof.aperture_fstop = rng.uniform(2.8, 8)
        ls = [area("key", (target.x + rng.uniform(-14, 14), target.y + rng.uniform(-6, 16),
                           rng.uniform(10, 22)), rng.uniform(3, 9), rng.uniform(1500, 4200),
                   (1.0, rng.uniform(0.8, 0.95), rng.uniform(0.6, 0.85)), target)]
        if rng.random() < 0.6:
            ls.append(area("fill", (target.x + rng.uniform(-16, 16), target.y - 12, 12),
                           10, rng.uniform(300, 1200), target=target))
        path = OUT / "raw" / f"{did}_p{k}.png"
        render_to(path)
        shots.append({"file": path.name, "kind": pname})
        for li in ls:
            bpy.data.objects.remove(li, do_unlink=True)
        gm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.12
    return shots


def main():
    rng = random.Random(SEED)
    (OUT / "catalog").mkdir(parents=True, exist_ok=True)
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    meta = []
    for f in range(FAMILIES):
        base = new_design(rng)
        fam = []
        for v in range(VARIANTS):
            d = base if v == 0 else mutate(base, rng, fam)
            fam.append(d)
            did = f"F{f:02d}V{v}"
            shots = make_one(did, d, rng)
            meta.append({"id": did, "family": f, "design": d, "shots": shots})
            (OUT / "meta.json").write_text(json.dumps(meta, indent=1, default=str),
                                          encoding="utf-8")
            print("✔", did, flush=True)


main()
