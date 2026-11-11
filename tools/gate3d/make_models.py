# -*- coding: utf-8 -*-
"""مجسّمات مشهد الدخول ثلاثي الأبعاد (5.3) — Blender 4.2 (حزمة bpy).

يبني بالهندسة الحقيقية — لا صوراً:
  · سبيكة صبٍّ (كيلو): منشورٌ مخروطي بحوافّ مشطوفة، وحقلٌ غائر في وجهها
    العلوي (ساتان) عليه ختمٌ بارز مصقول: شعار JADEITE ونقش «FINE GOLD ·
    999.9 · 1 KILO» ورقمٌ تسلسلي.
  · سبيكة سكّ (100 غرام): لوحٌ مستدير الأركان بإطارٍ بارز وختمٍ مثله.
  · شعار JADEITE نفسه مجسّماً: يُتتبَّع من `assets/logo_gold.png` (الحدود
    الخارجية والفتحات) ثم يُبثق بسماكة ويُشطف — فتلتقط حوافّه الضوء كقطعة
    ذهبٍ مصبوبة. ثلاثة أجزاء منفصلة (الرمز · الاسم · السطر العربي) لتتحرّك
    كلٌّ وحدها في المشهد.

الناتج (glTF ثنائي خام) في `tools/gate3d/build/`:  bars.glb · logo.glb
— يضغطه `build.mjs` (meshopt) ويضمّه إلى `assets/gate3d/data.js`.

الاستخدام (مرةً عند تعديل التصميم — البرنامج لا يحتاج Blender):
    python make_models.py            # بحزمة bpy 4.2 + opencv-python-headless
ثم:  node build.mjs                  # يجمع المشهد والمجسّمات للبرنامج
"""
import math
import os
import sys
from pathlib import Path

import bpy  # noqa: I001 — قبل bmesh: حزمة bpy تضيف مسار وحداتها
import bmesh
import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "build"
LOGO_PNG = ROOT / "assets" / "logo_gold.png"
FONT = HERE / "fonts" / "Cinzel_700Bold.ttf"

bpy.ops.wm.read_factory_settings(use_empty=True)
_font = bpy.data.fonts.load(str(FONT))


# ───────────────────────── المواد (أسماؤها تُقرأ في المشهد)
def _mat(name, rough):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (1.0, 0.766, 0.336, 1)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = rough
    return m


GOLD = _mat("Gold", 0.14)          # المصقول: الحوافّ والحروف البارزة
SATIN = _mat("GoldSatin", 0.38)    # الحقل الغائر تحت الختم


def _link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _finish(obj, angle=34.0):
    """حوافٌّ حادّة حيث الزاوية أكبر من `angle` وناعمةٌ فيما دونها."""
    me = obj.data
    for p in me.polygons:
        p.use_smooth = True
    try:
        me.set_sharp_from_angle(angle=math.radians(angle))
    except Exception:
        pass
    return obj


def _mesh_from(obj_src, name):
    """يحوّل منحنى/نصّاً إلى شبكة حقيقية (بعد البثق والشطف)."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(obj_src.evaluated_get(dg))
    me.name = name
    out = bpy.data.objects.new(name, me)
    out.matrix_world = obj_src.matrix_world.copy()
    bpy.data.objects.remove(obj_src)
    return _link(out)


def _text(body, size, depth, bevel, x=0.0, y=0.0, z=0.0, name="t",
          spacing=1.0):
    cu = bpy.data.curves.new(name + "_src", "FONT")
    cu.body = body
    cu.font = _font
    cu.size = size
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.space_character = spacing
    cu.extrude = depth
    cu.bevel_depth = bevel
    cu.bevel_resolution = 1
    cu.resolution_u = 5
    ob = _link(bpy.data.objects.new(name + "_src", cu))
    ob.location = (x, y, z + depth)
    me = _mesh_from(ob, name)
    me.data.materials.append(GOLD)
    return _finish(me, 40)


# ───────────────────────── تتبّع الشعار
def _trace(rows=None, scale=4, eps=1.1, min_area=60.0):
    """حدود الشعار (الخارجية والفتحات) من قناة الشفافية — بعد تكبيرٍ
    ونعومة، فلا تظهر درجاتُ البكسل على الحوافّ المشطوفة."""
    img = cv2.imread(str(LOGO_PNG), cv2.IMREAD_UNCHANGED)
    a = img[:, :, 3] if img.shape[2] == 4 else cv2.cvtColor(
        img, cv2.COLOR_BGR2GRAY)
    if rows is not None:
        a = a.copy()
        a[:rows[0], :] = 0
        a[rows[1]:, :] = 0
    a = cv2.resize(a, None, fx=scale, fy=scale,
                   interpolation=cv2.INTER_CUBIC)
    a = cv2.GaussianBlur(a, (0, 0), scale * 0.55)
    _, m = cv2.threshold(a, 120, 255, cv2.THRESH_BINARY)
    cs, _h = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cs:
        if abs(cv2.contourArea(c)) < min_area * scale * scale:
            continue
        c = cv2.approxPolyDP(c, eps * scale / 4.0, True)
        if len(c) >= 3:
            out.append(c[:, 0, :].astype(np.float64) / scale)
    return out, img.shape[1], img.shape[0]


def _logo_part(name, rows, width_units, depth, bevel, cx, cy, ppu):
    """جزءٌ من الشعار مجسّماً: منحنى ثنائي البعد بالتعبئة الزوجية
    (الفتحات تُفرَّغ تلقائياً) يُبثق ويُشطف ثم يُحوَّل شبكة."""
    cs, w, h = _trace(rows)
    cu = bpy.data.curves.new(name + "_src", "CURVE")
    cu.dimensions = "2D"
    cu.fill_mode = "BOTH"
    cu.extrude = depth
    cu.bevel_depth = bevel
    cu.bevel_resolution = 3
    cu.offset = 0.0
    for pts in cs:
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for i, (x, y) in enumerate(pts):
            sp.points[i].co = ((x - cx) / ppu, -(y - cy) / ppu, 0.0, 1.0)
        sp.use_cyclic_u = True
    ob = _link(bpy.data.objects.new(name + "_src", cu))
    # قائمٌ يواجه الكاميرا: وجهه (+Z في الرسم) يصير −Y في Blender = +Z في glTF
    ob.rotation_euler = (math.radians(90), 0, 0)
    me = _mesh_from(ob, name)
    me.data.materials.append(GOLD)
    return _finish(me, 30)


def build_logo():
    _cs, w, h = _trace()
    # كل الشعار بعرض وحدتين ونصف: الرمز فوق، والاسم، والسطر العربي
    ppu = w / 2.5
    cx, cy = w / 2.0, h * 0.47
    parts = [
        _logo_part("LogoEmblem", (0, 288), 2.5, 0.09, 0.012, cx, cy, ppu),
        _logo_part("LogoName", (288, 530), 2.5, 0.07, 0.009, cx, cy, ppu),
        _logo_part("LogoTagline", (530, h), 2.5, 0.05, 0.006, cx, cy, ppu),
    ]
    return parts


def stamp_emblem(size, z, name="StampEmblem", depth=0.008, bevel=0.0025):
    """الرمز وحده صغيراً مسطّحاً — ختمٌ على وجه السبيكة."""
    cs, w, h = _trace((0, 288))
    ppu = w / size
    cu = bpy.data.curves.new(name + "_src", "CURVE")
    cu.dimensions = "2D"
    cu.fill_mode = "BOTH"
    cu.extrude = depth
    cu.bevel_depth = bevel
    cu.bevel_resolution = 1
    for pts in cs:
        sp = cu.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for i, (x, y) in enumerate(pts):
            sp.points[i].co = ((x - w / 2) / ppu, -(y - 144) / ppu, 0, 1)
        sp.use_cyclic_u = True
    ob = _link(bpy.data.objects.new(name + "_src", cu))
    ob.location = (0, 0, z + depth)
    me = _mesh_from(ob, name)
    me.data.materials.append(GOLD)
    return _finish(me, 30)


# ───────────────────────── السبائك
def _field_faces(bm, top, thickness, depth):
    """يحفر حقلاً غائراً في الوجه العلوي ويعيده (لمادة الساتان)."""
    res = bmesh.ops.inset_individual(bm, faces=[top], thickness=thickness,
                                     depth=-depth, use_even_offset=True)
    return top


def cast_bar(name="BarCast"):
    """سبيكة صبٍّ كيلو: قاعدة 2.30×1.06، قمّة 2.02×0.80، ارتفاع 0.50."""
    L, W, H = 2.30, 1.06, 0.50
    tL, tW = 2.02, 0.80
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        if v.co.z > 0:
            v.co.x *= tL
            v.co.y *= tW
            v.co.z = H
        else:
            v.co.x *= L
            v.co.y *= W
            v.co.z = 0.0
    bmesh.ops.bevel(bm, geom=list(bm.edges), offset=0.045, segments=5,
                    profile=0.6, affect="EDGES", clamp_overlap=True)
    bm.faces.ensure_lookup_table()
    top = max(bm.faces, key=lambda f: (f.normal.z > 0.99) * f.calc_area())
    _field_faces(bm, top, 0.085, 0.022)
    bm.to_mesh(me)
    bm.free()
    ob = _link(bpy.data.objects.new(name, me))
    me.materials.append(GOLD)
    me.materials.append(SATIN)
    # الحقل الغائر ساتان: أعلى وجهٍ أفقيٍّ بعد الحفر
    zmax = max(p.center.z for p in me.polygons if p.normal.z > 0.99)
    for p in me.polygons:
        if p.normal.z > 0.99 and abs(p.center.z - (H - 0.022)) < 0.004:
            p.material_index = 1
    _finish(ob, 34)
    zf = H - 0.022
    parts = [ob,
             stamp_emblem(0.36, zf, "BarEmblem"),
             _text("JADEITE", 0.15, 0.009, 0.0025, 0, -0.30, zf,
                   "BarName", spacing=1.18),
             _text("FINE GOLD", 0.085, 0.007, 0.002, 0.52, 0.17, zf,
                   "BarFine", spacing=1.1),
             _text("999.9", 0.15, 0.009, 0.0025, 0.52, 0.0, zf,
                   "BarPurity"),
             _text("1 KILO", 0.085, 0.007, 0.002, 0.52, -0.17, zf,
                   "BarWeight", spacing=1.1),
             _text("JD 260114", 0.065, 0.006, 0.0015, -0.55, 0.0, zf,
                   "BarSerial", spacing=1.05)]
    for p in parts[2:]:
        if p.name.startswith("BarSerial"):
            p.rotation_euler = (0, 0, math.radians(90))
    parts[1].location.x = -0.55 + 0.0
    parts[1].location.y = 0.0
    # الرمز والاسم يساراً، والنقش يميناً، والرقم بينهما رأسياً
    parts[1].location = (-0.28, 0.06, zf)
    parts[2].location = (-0.28, -0.24, zf + 0.009)
    parts[6].location = (-0.78, 0.0, zf + 0.006)
    return _join(parts, name)


def mint_bar(name="BarMint"):
    """سبيكة سكٍّ 100 غرام: لوحٌ 1.00×0.58×0.075 مستدير الأركان."""
    L, W, T = 1.00, 0.58, 0.075
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= L
        v.co.y *= W
        v.co.z = (v.co.z + 0.5) * T
    vert_edges = [e for e in bm.edges
                  if abs(e.verts[0].co.z - e.verts[1].co.z) > 1e-6]
    bmesh.ops.bevel(bm, geom=vert_edges, offset=0.07, segments=8,
                    profile=0.5, affect="EDGES")
    bm.edges.ensure_lookup_table()
    flat = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z)
            < 1e-6]
    bmesh.ops.bevel(bm, geom=flat, offset=0.012, segments=3, profile=0.5,
                    affect="EDGES", clamp_overlap=True)
    bm.faces.ensure_lookup_table()
    top = max(bm.faces, key=lambda f: (f.normal.z > 0.99) * f.calc_area())
    _field_faces(bm, top, 0.045, 0.010)
    bm.to_mesh(me)
    bm.free()
    ob = _link(bpy.data.objects.new(name, me))
    me.materials.append(GOLD)
    me.materials.append(SATIN)
    for p in me.polygons:
        if p.normal.z > 0.99 and abs(p.center.z - (T - 0.010)) < 0.003:
            p.material_index = 1
    _finish(ob, 34)
    zf = T - 0.010
    parts = [ob,
             stamp_emblem(0.20, zf, "MintEmblem", 0.006, 0.0018),
             _text("JADEITE", 0.075, 0.006, 0.0016, 0, -0.03, zf,
                   "MintName", spacing=1.18),
             _text("100 g · 999.9", 0.05, 0.005, 0.0012, 0, -0.15, zf,
                   "MintFine", spacing=1.05)]
    parts[1].location = (0, 0.13, zf)
    return _join(parts, name)


def _join(parts, name):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in parts:
        o.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    ob.data.name = name
    return ob


def _clean(ob):
    """شبكةٌ سليمة: بلا رؤوسٍ مكرّرة ولا أوجهٍ متداعية (نتاج الدمج)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-6)
    bm.to_mesh(ob.data)
    bm.free()
    ob.data.validate(clean_customdata=False)
    _finish(ob, 34 if ob.name.startswith("Bar") else 30)


def export(objs, path):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in objs:
        _clean(o)
        o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(path), export_format="GLB", use_selection=True,
        export_apply=True, export_yup=True, export_normals=True,
        export_texcoords=False, export_materials="EXPORT",
        # الضغط بـ gltfpack بعدها (meshopt) — Draco ليس في حزمة bpy
        export_draco_mesh_compression_enable=False)


def _tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    bars = [cast_bar(), mint_bar()]
    bars[1].location = (0, 3.0, 0)          # بعيدةٌ عن الأولى في الملف
    for b in bars:
        print(f"  {b.name}: {_tris(b):,} مثلث")
    export(bars, OUT / "bars.glb")
    for o in list(bpy.context.scene.objects):
        bpy.data.objects.remove(o)
    logo = build_logo()
    for p in logo:
        print(f"  {p.name}: {_tris(p):,} مثلث")
    export(logo, OUT / "logo.glb")
    for f in ("bars.glb", "logo.glb"):
        print(f"  ✔ {f}: {(OUT / f).stat().st_size / 1024:,.0f} ك.ب")


if __name__ == "__main__":
    main()
