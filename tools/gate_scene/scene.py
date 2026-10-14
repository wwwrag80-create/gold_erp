"""مشهد سبائك الذهب لبوابة الدخول (4.70) — Blender 4.2 · Cycles.

التركيب نفسه (مواضع السبائك والخاتم ومسار الكاميرا والإضاءة) — والذي
تغيّر هو ما يصنع الواقعية:
  · ذهبٌ فيزيائي (لون الانعكاس العمودي F0 ولون الحافّة F82) بلا نتوءٍ
    مجهري يومض بين الإطارات، وخشونةٌ متفاوتة على مدى واسع فقط.
  · ختمٌ كختم المصافي: حروفٌ وإطارٌ مصقولة على أرضيةٍ «ساتان» مطفأة —
    التباين بين اللمعان والإطفاء هو ما يجعل الحروف حادّة مقروءة.
  · خاتمٌ حقيقي بمقطع «كومفورت فِت» (قبّةٌ خارجية وداخلٌ مسطّح) لا كعكة.
  · سطحٌ أسود بطبقة لكّ لامعة فوق قاعدةٍ ساتان، وبقعةُ ضوءٍ خافتة تحت
    الذهب تُظهر ظلال التماس الحقيقية.
  · بطاقات انعكاس كبيرة خافتة (كاستوديو المنتجات) تملأ أوجه الذهب.
  · 1920×1080 · 30 إطاراً/ث · 48 عيّنة تكيّفية · مزيل ضوضاء OIDN بممرّي
    اللون والاتجاه · بذرةٌ ثابتة (لا يغلي التشويش بين الإطارات) · ضبابية
    حركة بغالق 180° · مخرج PNG بعمق 16 بت (لا تدرّج متدرّج قبل الضغط).

الاستخدام (الإطارات المصيَّرة تُتخطّى — فالتصيير يُستأنف إن انقطع):
  blender -b -P scene.py -- OUTDIR 240 1920 1080 48
  python scene.py OUTDIR 240 1920 1080 48          (بحزمة bpy 4.2)
  python scene.py OUTDIR 240 1920 1080 48 --frames 1,61,121
ثم: python encode.py OUTDIR gold_loop.webp gold_poster.jpg 92
ومقابض التجربة متغيّرات بيئة (KEY · STRIP · RIM · VIEW · BORDER …).
"""
import math, sys, os, time
import bpy, bmesh
from mathutils import Vector, Euler

# يعمل من بايثون (حزمة bpy) أو من Blender نفسه: blender -b -P scene.py -- …
A_ = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
OUT, N, W, H, SPP = A_[0], int(A_[1]), int(A_[2]), int(A_[3]), int(A_[4])
PICK = None
if "--frames" in A_:
    PICK = [int(x) for x in A_[A_.index("--frames") + 1].split(",")]
    F0, F1 = 1, N
else:
    F0 = int(A_[5]) if len(A_) > 5 else 1
    F1 = int(A_[6]) if len(A_) > 6 else N
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
ENV = lambda k, d: float(os.environ.get(k, d))

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

# ───────────────────────── المواد
GOLD_F0 = (1.0, 0.766, 0.336, 1)        # ذهب 24: الانعكاس العمودي (خطّي)
GOLD_F82 = (1.0, 0.92, 0.74, 1)         # يبيضّ قليلاً عند الحوافّ المائلة


def mat_gold(name, rough=0.12, rvar=0.03, scale=6.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; n = nt.nodes; l = nt.links
    b = n["Principled BSDF"]
    b.inputs["Base Color"].default_value = GOLD_F0
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Specular Tint"].default_value = GOLD_F82
    # تفاوتٌ واسعٌ هادئ في الخشونة — كسطحٍ لُمّع باليد — بلا تفاصيل
    # مجهرية: النقش المجهري يومض بين الإطارات ويتحوّل إلى «غليان»
    tex = n.new("ShaderNodeTexNoise"); tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = 1.5
    mr = n.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = rough - rvar * 0.5
    mr.inputs["To Max"].default_value = rough + rvar * 0.5
    l.new(tex.outputs["Fac"], mr.inputs["Value"])
    l.new(mr.outputs["Result"], b.inputs["Roughness"])
    return m


def mat_floor():
    m = bpy.data.materials.new("BlackLacquer"); m.use_nodes = True
    nt = m.node_tree; n = nt.nodes; l = nt.links
    b = n["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.0032, 0.0028, 0.0024, 1)
    b.inputs["Roughness"].default_value = 0.35
    # القاعدة تحت اللكّ تكاد لا تعكس: بلا هذا تنتشر تحت الذهب هالةٌ
    # بنّية عريضة — والانعكاس الحادّ تتكفّل به طبقة اللكّ وحدها
    b.inputs["Specular IOR Level"].default_value = ENV("FSPEC", 0.12)
    # طبقة لكٍّ صافية: انعكاسٌ حادّ للذهب فوق قاعدةٍ سوداء ساتان
    b.inputs["Coat Weight"].default_value = 0.0 if os.environ.get("NOCOAT") else 1.0
    b.inputs["Coat IOR"].default_value = 1.5
    tex = n.new("ShaderNodeTexNoise"); tex.inputs["Scale"].default_value = 2.5
    tex.inputs["Detail"].default_value = 1.0
    mr = n.new("ShaderNodeMapRange")
    mr.inputs["To Min"].default_value = 0.028; mr.inputs["To Max"].default_value = 0.055
    l.new(tex.outputs["Fac"], mr.inputs["Value"])
    l.new(mr.outputs["Result"], b.inputs["Coat Roughness"])
    return m


GOLD = mat_gold("CastGold", rough=0.13, rvar=0.035)
GOLD_SATIN = mat_gold("SatinField", rough=ENV("SATIN", 0.30), rvar=0.04, scale=40.0)
GOLD_POLISH = mat_gold("PolishedStamp", rough=0.055, rvar=0.015)
GOLD_RING = mat_gold("PolishedRing", rough=0.035, rvar=0.012, scale=12.0)
FLOOR = mat_floor()

# ───────────────────────── السبيكة
def bar(name, L, Wd, Hh, taper=0.9, bevel=0.0022):
    bm = bmesh.new()
    lt, wt = L * taper, Wd * (taper - 0.07)
    pts = [(-L/2, -Wd/2, 0), (L/2, -Wd/2, 0), (L/2, Wd/2, 0), (-L/2, Wd/2, 0),
           (-lt/2, -wt/2, Hh), (lt/2, -wt/2, Hh), (lt/2, wt/2, Hh), (-lt/2, wt/2, Hh)]
    v = [bm.verts.new(p) for p in pts]
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        bm.faces.new([v[i] for i in f])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
    # حوافٌّ مدوّرة بثمانية مقاطع: لمعةٌ متّصلة ناعمة على كل حافّة
    bv = ob.modifiers.new("bevel", "BEVEL"); bv.width = bevel; bv.segments = 8
    bv.limit_method = "ANGLE"; bv.harden_normals = True
    ob.data.materials.append(GOLD)
    for p in ob.data.polygons: p.use_smooth = True
    return ob, lt, wt, Hh


def _plate(name, w, h, z, mat, thick=0.00002):
    bm = bmesh.new()
    vs = [bm.verts.new(p) for p in ((-w/2, -h/2, 0), (w/2, -h/2, 0), (w/2, h/2, 0), (-w/2, h/2, 0))]
    bm.faces.new(vs)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
    ob.data.materials.append(mat); ob.location = (0, 0, z + thick)
    return ob


def stamp(parent, lt, wt, Hh, lines, serial):
    """ختم المصفاة: إطارٌ وحروفٌ مصقولة بارزة على أرضيةٍ ساتان."""
    z = Hh
    objs = []
    fw, fh, t = lt * 0.80, wt * 0.78, 0.0009
    # أرضية الختم المطفأة داخل الإطار
    objs.append(_plate("field", fw - 2 * t, fh - 2 * t, z, GOLD_SATIN))
    bm = bmesh.new()
    def rect(x0, y0, x1, y1):
        return [bm.verts.new((x0, y0, 0)), bm.verts.new((x1, y0, 0)),
                bm.verts.new((x1, y1, 0)), bm.verts.new((x0, y1, 0))]
    o = rect(-fw/2, -fh/2, fw/2, fh/2); i = rect(-fw/2 + t, -fh/2 + t, fw/2 - t, fh/2 - t)
    for k in range(4):
        bm.faces.new([o[k], o[(k+1) % 4], i[(k+1) % 4], i[k]])
    me = bpy.data.meshes.new("frame"); bm.to_mesh(me); bm.free()
    fr = bpy.data.objects.new("frame", me); sc.collection.objects.link(fr)
    sol = fr.modifiers.new("s", "SOLIDIFY"); sol.thickness = 0.00045; sol.offset = 1.0
    fb = fr.modifiers.new("b", "BEVEL"); fb.width = 0.00010; fb.segments = 3
    fr.data.materials.append(GOLD_POLISH); fr.location = (0, 0, z - 0.00002); objs.append(fr)
    font = bpy.data.fonts.load(SERIF)
    for txt, size, y in lines + [(serial, wt * 0.075, -fh * 0.36)]:
        cu = bpy.data.curves.new("t", "FONT"); cu.body = txt; cu.font = font
        cu.size = size; cu.align_x = "CENTER"; cu.align_y = "CENTER"
        # حروفٌ أعمق بحافّةٍ مشطوفة دقيقة: تلتقط الضوء خطّاً لامعاً حادّاً
        cu.extrude = 0.00024; cu.bevel_depth = 0.00006; cu.bevel_resolution = 2
        cu.resolution_u = 24
        ob = bpy.data.objects.new("t", cu); sc.collection.objects.link(ob)
        ob.data.materials.append(GOLD_POLISH)
        ob.location = (0, y, z + 0.00024 - 0.00002)
        objs.append(ob)
    for ob in objs:
        ob.parent = parent
    return objs


def place(ob, loc, rot_deg):
    ob.location = loc; ob.rotation_euler = Euler((0, 0, math.radians(rot_deg)))


KG = dict(L=0.118, Wd=0.054, Hh=0.019)
A, lta, wta, ha = bar("BarA", **KG)
B, ltb, wtb, hb = bar("BarB", **KG)
C, ltc, wtc, hc = bar("BarC", **KG)
LINES = lambda lt, wt: [("FINE GOLD", wt * 0.17, wt * 0.20), ("999.9", wt * 0.24, -wt * 0.02),
                        ("1 KILO", wt * 0.11, -wt * 0.20)]
for ob, lt, wt, hh, s in ((A, lta, wta, ha, "N° 418 520"), (B, ltb, wtb, hb, "N° 418 521"),
                          (C, ltc, wtc, hc, "N° 418 522")):
    stamp(ob, lt, wt, hh, LINES(lt, wt), s)
place(A, (-0.040, 0.012, 0), -9)
place(B, (0.030, 0.040, 0), 6)
place(C, (-0.004, 0.026, KG["Hh"] * 0.995), -3)
C.rotation_euler = Euler((math.radians(0.6), 0, math.radians(-3)))
S, lts, wts, hs = bar("BarS", L=0.060, Wd=0.032, Hh=0.0095, bevel=0.0013)
stamp(S, lts, wts, hs, [("FINE GOLD", wts * 0.16, wts * 0.19), ("999.9", wts * 0.22, -wts * 0.02),
                         ("100 g", wts * 0.12, -wts * 0.21)], "N° 07 316")
place(S, (0.050, -0.055, 0), 24)

# ───────────────────────── الخاتم: مقطع «كومفورت فِت»
def ring(name, ri, ro, hgt, seg=320, prof=72):
    """قبّةٌ خارجية مدوّرة وداخلٌ شبه مسطّح — مقطع دبلة الذهب الحقيقية."""
    rm, zm = (ri + ro) / 2, hgt / 2
    a, b = (ro - ri) / 2, hgt / 2
    pts = []
    for k in range(prof):
        th = 2 * math.pi * k / prof
        c, s = math.cos(th), math.sin(th)
        n = 2.25 if c >= 0 else 4.0          # الخارج قبّة، والداخل مريح مسطّح
        r = rm + a * math.copysign(abs(c) ** (2 / n), c)
        z = zm + b * math.copysign(abs(s) ** (2 / 2.6), s)
        pts.append((r, z))
    bm = bmesh.new()
    rings = []
    for j in range(seg):
        ph = 2 * math.pi * j / seg
        cp, sp = math.cos(ph), math.sin(ph)
        rings.append([bm.verts.new((r * cp, r * sp, z)) for r, z in pts])
    for j in range(seg):
        r0, r1 = rings[j], rings[(j + 1) % seg]
        for k in range(prof):
            bm.faces.new((r0[k], r0[(k + 1) % prof], r1[(k + 1) % prof], r1[k]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for p in me.polygons: p.use_smooth = True
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
    ob.data.materials.append(GOLD_RING)
    return ob


R = ring("Ring", ri=0.0118, ro=0.0166, hgt=0.0050)
R.location = (-0.040, -0.060, 0.00003)

# ───────────────────────── الأرضية والخلفية
bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, 0))
fl = bpy.context.active_object; fl.data.materials.append(FLOOR)
w = bpy.data.worlds.new("W"); sc.world = w; w.use_nodes = True
bg = w.node_tree.nodes["Background"]; bg.inputs["Color"].default_value = (0.0016, 0.0012, 0.0008, 1)
bg.inputs["Strength"].default_value = 1.0

# ───────────────────────── الإضاءة (استوديو منتجات)
GOLD_ONLY = bpy.data.collections.new("GoldReceivers")
WITH_FLOOR = bpy.data.collections.new("GoldAndFloor")
for ob in list(sc.collection.objects):
    if ob.type in ("MESH", "FONT") and ob is not fl:
        GOLD_ONLY.objects.link(ob); WITH_FLOOR.objects.link(ob)
WITH_FLOOR.objects.link(fl)
FLOOR_ONLY = bpy.data.collections.new("FloorOnly")
FLOOR_ONLY.objects.link(fl)


def area(name, size, size_y, loc, target, color, power, shape="RECTANGLE", floor=False):
    ld = bpy.data.lights.new(name, "AREA"); ld.shape = shape; ld.size = size; ld.size_y = size_y
    ld.color = color; ld.energy = power
    ob = bpy.data.objects.new(name, ld); sc.collection.objects.link(ob)
    ob.location = loc
    d = Vector(target) - Vector(loc); ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    ob.visible_camera = False
    if not os.environ.get("NOLL"):
        ob.light_linking.receiver_collection = (FLOOR_ONLY if floor == "only" else
                                                WITH_FLOOR if floor else GOLD_ONLY)
    return ob


CENTER = Vector((-0.005, 0.0, 0.015))
# المفتاح أخفّ مما كان: الأوجه العليا تبقى ذهباً مشبعاً لا أبيضَ محترقاً
key = area("Key", 0.60, 0.35, (-0.22, -0.18, 0.52), CENTER, (1.0, 0.95, 0.88), ENV("KEY", 4.5))
strip = area("Strip", 1.10, 0.045, (0.0, 0.18, 0.34), CENTER, (1.0, 0.97, 0.92), ENV("STRIP", 6))
rim = area("Rim", 0.8, 0.07, (0.10, 0.55, 0.14), CENTER + Vector((0, 0, 0.01)), (1.0, 0.93, 0.84), ENV("RIM", 6))
HCOL = tuple(float(v) for v in os.environ.get("HCOL", "1.0,0.84,0.62").split(","))
strip.data.energy = ENV("STRIP", 6) * 0.965     # ثابتة: اللمعة تعبر بحركة الشريط وحدها
horizon = area("Horizon", 2.6, 0.55, (0.0, 1.9, 0.10), (0.0, 0.0, 0.0), HCOL, ENV("HORIZON", 0.6),
               shape="ELLIPSE", floor="only")
fill = area("Fill", 0.9, 0.9, (0.45, -0.55, 0.20), CENTER, (1.0, 0.90, 0.80), 1.2)
kick = area("Kick", 0.25, 0.04, (-0.36, 0.18, 0.05), CENTER, (1.0, 0.82, 0.60), ENV("KICK", 5))
# بطاقة انعكاسٍ علوية واسعة خافتة: تدرّجٌ ناعم على الأوجه العليا بدل السواد
top = area("TopCard", 1.0, 0.6, (0.05, -0.05, 0.95), CENTER, (1.0, 0.94, 0.86), ENV("TOP", 0.4))
# بقعةُ ضوءٍ خافتة على السطح تحت الذهب: ظلال تماسٍ حقيقية حوله
pool = area("FloorPool", 0.35, 0.35, (-0.18, -0.12, 0.62), Vector((-0.01, -0.01, 0.0)),
            (1.0, 0.86, 0.66), ENV("POOL", 2.0), shape="DISK", floor="only")
# لمعةٌ للخاتم وحده: قوسٌ مضيء على قبّته — بلا هذا يعكس سواد المكان
RING_ONLY = bpy.data.collections.new("RingOnly"); RING_ONLY.objects.link(R)
rk = area("RingKick", 0.30, 0.05, (-0.20, -0.30, 0.10), Vector(R.location) + Vector((0, 0, 0.003)),
          (1.0, 0.95, 0.86), ENV("RINGKICK", 6.0))
if not os.environ.get("NOLL"):
    rk.light_linking.receiver_collection = RING_ONLY

# ───────────────────────── الكاميرا (المسار نفسه)
cd = bpy.data.cameras.new("Cam"); cd.lens = 80; cd.sensor_width = 36
# عمق ميدانٍ يحفظ السبائك والخاتم حادّة معاً، والخلفية سوداء على أي حال
cd.dof.use_dof = not os.environ.get("NODOF"); cd.dof.aperture_fstop = 7.1; cd.dof.aperture_blades = 7
cam = bpy.data.objects.new("Cam", cd); sc.collection.objects.link(cam); sc.camera = cam
focus = bpy.data.objects.new("Focus", None); sc.collection.objects.link(focus)
focus.location = (-0.008, 0.004, 0.030)
cd.dof.focus_object = focus
aim = bpy.data.objects.new("Aim", None); sc.collection.objects.link(aim)
tc = cam.constraints.new("TRACK_TO"); tc.target = aim; tc.track_axis = "TRACK_NEGATIVE_Z"; tc.up_axis = "UP_Y"


def pose(t):
    """t ∈ [0,1): حركةٌ دورية مغلقة — أول إطارٍ يلي آخرها بلا قفزة."""
    w = 2 * math.pi * t
    az = math.radians(-22 + 5.0 * math.sin(w))
    el = math.radians(19.0 + 1.4 * math.sin(w + 1.3))
    d = 1.07 + 0.04 * math.cos(w)
    cam.location = (CENTER.x + d * math.sin(az) * math.cos(el),
                    CENTER.y - d * math.cos(az) * math.cos(el),
                    CENTER.z + d * math.sin(el))
    aim.location = (CENTER.x + 0.124 + 0.004 * math.sin(w + 0.5), CENTER.y + 0.03, CENTER.z - 0.010)
    sx = 0.30 * math.sin(w + 0.7)
    strip.location = (sx, 0.17, 0.34)
    strip.rotation_euler = (Vector(CENTER) + Vector((sx * 0.35, 0, 0)) - strip.location).to_track_quat("-Z", "Y").to_euler()


def key_pose(f):
    """مفاتيح الحركة لكل إطار — تُدرج فتعمل ضبابية الحركة من الحركة الحقيقية."""
    pose((f - 1) / float(N))
    for ob in (cam, aim, strip):
        ob.keyframe_insert("location", frame=f)
    strip.keyframe_insert("rotation_euler", frame=f)


# ───────────────────────── التصيير
sc.render.engine = "CYCLES"
cy = sc.cycles
cy.device = "CPU"
# تسعة أضواء مساحية فقط: الاختيار بالقدرة أسرع من شجرة الأضواء بلا ضوضاءٍ زائدة
cy.use_light_tree = bool(os.environ.get("LT"))
cy.samples = SPP
cy.use_adaptive_sampling = True
cy.adaptive_threshold = ENV("ATH", 0.015)
cy.adaptive_min_samples = int(ENV("AMIN", 16))
cy.use_denoising = True
cy.denoiser = "OPENIMAGEDENOISE"
cy.denoising_input_passes = "RGB_ALBEDO_NORMAL"
cy.denoising_prefilter = "ACCURATE"
if hasattr(cy, "denoising_quality"):
    cy.denoising_quality = "HIGH"
# بذرةٌ ثابتة: التشويش المتبقّي يبقى في مكانه فلا «يغلي» بين الإطارات
cy.seed = int(ENV("SEED", 7))
cy.use_animated_seed = False
cy.max_bounces = int(ENV("MB", 8)); cy.glossy_bounces = int(ENV("GB", 6)); cy.diffuse_bounces = int(ENV("DB", 2))
cy.transparent_max_bounces = 4; cy.transmission_bounces = 2
cy.caustics_reflective = False; cy.caustics_refractive = False
cy.blur_glossy = 0.7
cy.sample_clamp_direct = 0.0
cy.sample_clamp_indirect = 6.0          # لا شرارات عابرة تومض
cy.filter_width = 1.5
sc.render.use_persistent_data = True
# غالق 180° — ضبابية حركةٍ طبيعية للكاميرا كتصوير السينما
sc.render.use_motion_blur = not os.environ.get("NOMB")
sc.render.motion_blur_shutter = 0.5
sc.render.resolution_x = W; sc.render.resolution_y = H; sc.render.resolution_percentage = 100
if os.environ.get("BORDER"):                # تصيير جزءٍ من الإطار للتجارب
    x0, y0, x1, y1 = [float(v) for v in os.environ["BORDER"].split(",")]
    sc.render.use_border = True; sc.render.use_crop_to_border = True
    sc.render.border_min_x, sc.render.border_min_y = x0, y0
    sc.render.border_max_x, sc.render.border_max_y = x1, y1
sc.render.film_transparent = False
VT = os.environ.get("VIEW", "Khronos PBR Neutral")
sc.view_settings.view_transform = VT
sc.view_settings.look = "AgX - Punchy" if VT == "AgX" else "None"
sc.view_settings.exposure = ENV("EXPO", 0.0)
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGB"
sc.render.image_settings.color_depth = "16"
sc.render.image_settings.compression = 15
sc.use_nodes = True
nt = sc.node_tree; rl = nt.nodes["Render Layers"]; comp = nt.nodes["Composite"]
gl = nt.nodes.new("CompositorNodeGlare"); gl.glare_type = "FOG_GLOW"; gl.quality = "HIGH"
gl.threshold = 3.0; gl.size = 6; gl.mix = -0.96
nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
# ══ سوادٌ حقيقي مع ذهبٍ مشبع ══
# «Khronos PBR Neutral» صُمّم لتصوير المنتجات: يحفظ لون المادة في
# اللمعات فيبقى الذهب ذهباً لا أبيضَ باهتاً — لكنه يرفع الأسود قليلاً.
# فيُضاف «كعبٌ» ناعم قبل التحويل: y = x² / (x + k) — قرب الصفر يهبط إلى
# السواد، وما فوق ذلك يكاد لا يتغيّر (y ≈ x − k). منحنى أملس بلا قصّ،
# فلا تظهر حدودٌ متدرّجة في الظلال.
TOE = ENV("TOE", 0.008)
src = gl.outputs["Image"]
if TOE > 0:
    sep = nt.nodes.new("CompositorNodeSeparateColor")
    cmb = nt.nodes.new("CompositorNodeCombineColor")
    nt.links.new(src, sep.inputs["Image"])
    for ch in ("Red", "Green", "Blue"):
        sq = nt.nodes.new("CompositorNodeMath"); sq.operation = "MULTIPLY"
        ad = nt.nodes.new("CompositorNodeMath"); ad.operation = "ADD"
        dv = nt.nodes.new("CompositorNodeMath"); dv.operation = "DIVIDE"
        ad.inputs[1].default_value = TOE
        nt.links.new(sep.outputs[ch], sq.inputs[0]); nt.links.new(sep.outputs[ch], sq.inputs[1])
        nt.links.new(sep.outputs[ch], ad.inputs[0])
        nt.links.new(sq.outputs[0], dv.inputs[0]); nt.links.new(ad.outputs[0], dv.inputs[1])
        nt.links.new(dv.outputs[0], cmb.inputs[ch])
    nt.links.new(sep.outputs["Alpha"], cmb.inputs["Alpha"])
    src = cmb.outputs["Image"]
nt.links.new(src, comp.inputs["Image"])

sc.frame_start, sc.frame_end = 1, N
sc.render.fps = 30
# مفتاحٌ قبل الأول وبعد الأخير (الحركة دورية): ضبابية الحركة عند ملتقى
# الحلقة متناظرة كسائر الإطارات
for f in range(0, N + 2):
    key_pose(f)
# المنحنيات خطّية بين المفاتيح (الحركة نفسها جيبية عند كل إطار)
for ob in (cam, aim, strip):
    if ob.animation_data and ob.animation_data.action:
        for fc in ob.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"

os.makedirs(OUT, exist_ok=True)
frames = PICK if PICK else range(F0, F1 + 1)
for f in frames:
    out = os.path.join(OUT, f"f{f:04d}.png")
    if os.path.exists(out):
        continue
    t0 = time.time()
    sc.frame_set(f)
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print(f"frame {f}/{N} {time.time()-t0:.1f}s", flush=True)
