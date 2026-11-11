// مشهد بوابة JADEITE ثلاثي الأبعاد (5.3) — three.js + GSAP، يُعرض حيّاً لا مقطعاً.
//
// · السبائك مجسّماتٌ حقيقية من Blender (glTF مضغوط بـ meshopt) بمادّة ذهبٍ
//   فيزيائية: لون الانعكاس العمودي للذهب، وخشونةٌ متفاوتة دقيقة، وختمٌ مصقول
//   على حقلٍ ساتان.
// · الإضاءة: بيئةٌ من Poly Haven (CC0) مع صناديق ضوء استوديو تُدمج في خريطة
//   انعكاسٍ واحدة (PMREM) — فتظهر على أوجه الذهب لمعاتٌ طويلةٌ حادّة كتصوير
//   المنتجات — وضوءٌ رئيسي بظلالٍ ناعمة.
// · الأرض: سطحٌ أسود لامع بانعكاسٍ حقيقي (مرآةٌ مستوية تُصيَّر كل إطار) مع
//   نعومةٍ وتلاشٍ بالبعد، وظلّ تماسٍ تحت السبائك.
// · جسيماتُ ذهبٍ تسبح في شعاع ضوءٍ مائل، وتوهّجٌ (Bloom) وحبيبٌ سينمائي
//   وتعتيمُ أطراف، وتحويل ألوانٍ «Neutral» يحفظ لون الذهب في اللمعات.
// · الشعار مجسّماً في طبقةٍ خاصة تُوضع حيث يطلب البرنامج (يمين الشاشة)،
//   يظهر من العتمة ويستدير ثم تعبره لمعة.
// · الكاميرا تقترب ببطءٍ ثم تدور حول السبائك ذهاباً وإياباً (GSAP).
//
// الصلة بالبرنامج (`window.gate3d`): start · setLogoRect · setExit · pause ·
// resume — والإبلاغ برسائل وحدة التحكّم «GATE3D:…».

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { EXRLoader } from 'three/addons/loaders/EXRLoader.js';
import { Reflector } from 'three/addons/objects/Reflector.js';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { gsap } from 'gsap';
import studioExr from '@pmndrs/assets/hdri/studio.exr.js';

const DATA = window.GATE3D_DATA || {};
const say = (m) => { try { console.log('GATE3D:' + m); } catch (e) { /* */ } };
const Q = new URLSearchParams(location.search);
const STILL = Q.has('still');                  // لقطةٌ ثابتة للاختبار
const T0 = Number(Q.get('t') || 0);            // ثانيةٌ بعينها من المشهد
const OFF = new Set((Q.get('off') || '').split(','));   // إطفاء طبقةٍ للفحص

// ══════════════════════════════ العارض
const canvas = document.getElementById('c');
let renderer;
try {
  renderer = new THREE.WebGLRenderer({
    canvas, antialias: false, alpha: false, stencil: false,
    powerPreference: 'high-performance', preserveDrawingBuffer: STILL,
  });
} catch (e) {
  say('nogl ' + (e && e.message));
  throw e;
}
if (!renderer.capabilities.isWebGL2) { say('nogl webgl1'); throw new Error('webgl2'); }
// رسمٌ بالمعالج لا بكرت الشاشة (كرتٌ محظور أو بلا تعريف): المشهد يثقل الجهاز
// كله — فالمقطع المصوَّر أولى به (إلا إن طُلب صراحةً للاختبار: ?soft)
const GPU = (() => {
  try {
    const gl = renderer.getContext();
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    return String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
  } catch (e) { return ''; }
})();
if (/swiftshader|llvmpipe|softpipe|software|basic render/i.test(GPU) && !Q.has('soft')) {
  say('nogl software ' + GPU);
  throw new Error('software');
}
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.NeutralToneMapping;
renderer.toneMappingExposure = STILL ? 1.0 : 0.0;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
let PR = Math.min(window.devicePixelRatio || 1, 1.5);
renderer.setPixelRatio(PR);

const scene = new THREE.Scene();
const logoScene = new THREE.Scene();

// ══════════════════════════════ البيئة: Poly Haven + صناديق ضوء
function b64buf(s) {
  const bin = atob(s.slice(s.indexOf(',') + 1));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

function hdriTexture() {
  const d = new EXRLoader().setDataType(THREE.HalfFloatType).parse(b64buf(studioExr));
  const t = new THREE.DataTexture(d.data, d.width, d.height, d.format, d.type);
  t.colorSpace = THREE.LinearSRGBColorSpace;
  t.minFilter = THREE.LinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.generateMipmaps = false;
  t.flipY = false;
  t.mapping = THREE.EquirectangularReflectionMapping;
  t.needsUpdate = true;
  return t;
}

function studioEnvironment() {
  // غرفةٌ داكنة: كرةٌ بصورة Poly Haven خافتة (ثراءٌ في الانعكاس) وصناديقُ ضوءٍ
  // كبيرة ناعمة الحوافّ (لمعاتٌ طويلةٌ حادّة على أوجه الذهب)
  const env = new THREE.Scene();
  const hdr = hdriTexture();
  // الصورة خافتةٌ ومقصوصة القمم: تعطي الذهب ثراءً وتنوّعاً في الانعكاس، أمّا
  // اللمعات الحادّة فمن صناديق الضوء وحدها (لا بقعٌ بيضاء من مصابيح الصورة)
  const sky = new THREE.Mesh(
    new THREE.SphereGeometry(20, 48, 24),
    new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, uniforms: { map: { value: hdr } },
      vertexShader: 'varying vec3 vD; void main(){ vD = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: `uniform sampler2D map; varying vec3 vD;
        void main(){ vec3 d = normalize(vD);
          vec2 uv = vec2(atan(d.z, d.x) * 0.1591549 + 0.5, asin(clamp(d.y, -1.0, 1.0)) * 0.3183099 + 0.5);
          vec3 c = texture2D(map, uv).rgb * vec3(0.22, 0.2, 0.18);
          gl_FragColor = vec4(min(c, vec3(1.1)), 1.0); }`,
    }));
  env.add(sky);
  const box = (w, h, x, y, z, k, tint = [1, 0.96, 0.9]) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(tint[0] * k, tint[1] * k, tint[2] * k), side: THREE.DoubleSide }));
    m.position.set(x, y, z);
    m.lookAt(0, 0.6, 0);
    env.add(m);
    return m;
  };
  box(7, 2.2, -4.5, 7.5, 3.5, 1.9);                 // المفتاح: فوق اليسار
  box(1.4, 9, 7.5, 3.5, -5, 3.4, [1, 0.92, 0.8]);   // شريط الحافّة: خلف اليمين
  box(9, 3, 0, 10, -1, 0.9);                        // سقفٌ مضيء
  box(16, 4.5, 0, 2.6, 10, 0.95, [1, 0.84, 0.62]);  // لوحٌ دافئ أمامي: الأوجه الطويلة ذهبٌ لا ظلّ
  box(3, 1.2, 6, 1.2, 8, 2.2, [1, 0.9, 0.75]);      // لمعةٌ صغيرة على الحوافّ اليمنى
  box(5, 4.5, 9.5, 2.6, 2.5, 0.8, [1, 0.86, 0.66]);  // جانبٌ أيمن: أوجه الرصّة المائلة
  box(16, 2.6, 0, 2.2, -10, 0.85, [1, 0.88, 0.7]);  // خلفيٌّ منخفض: لمعانُ الأوجه العليا والختم
  box(1.0, 6, -8, 3, -3, 1.8, [1, 0.9, 0.75]);      // شريطٌ يسار خلفي
  const pm = new THREE.PMREMGenerator(renderer);
  const rt = pm.fromScene(env, 0.03);
  pm.dispose();
  hdr.dispose();
  return rt.texture;
}

// ══════════════════════════════ مادة الذهب
const GOLD = new THREE.Color(1.0, 0.766, 0.336);     // F0 الذهب (خطّي)

function goldMaterial(rough, opts = {}) {
  const m = new THREE.MeshPhysicalMaterial({
    color: GOLD, metalness: 1.0, roughness: rough, envMapIntensity: 1.0,
    specularIntensity: 1.0, ...opts,
  });
  // تفاوتٌ دقيق في الخشونة وخدوشُ تلميعٍ خفيّة من موضع النقطة في الفضاء —
  // بلا صور: اللمعة تتكسّر قليلاً كما على معدنٍ حقيقي لُمّع باليد
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uSweep = m.userData.sweep || { value: -9.0 };
    sh.uniforms.uSweepGain = m.userData.sweepGain || { value: 0.0 };
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vWPos;')
      .replace('#include <worldpos_vertex>',
        '#include <worldpos_vertex>\nvWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
varying vec3 vWPos;
uniform float uSweep;
uniform float uSweepGain;
float h3(vec3 p){ p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float n3(vec3 x){ vec3 i = floor(x); vec3 f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(h3(i), h3(i + vec3(1,0,0)), f.x), mix(h3(i + vec3(0,1,0)), h3(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(h3(i + vec3(0,0,1)), h3(i + vec3(1,0,1)), f.x), mix(h3(i + vec3(0,1,1)), h3(i + vec3(1,1,1)), f.x), f.y), f.z); }`)
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
float nz = n3(vWPos * 3.1) * 0.6 + n3(vWPos * 11.0) * 0.4;
float scr = smoothstep(0.82, 1.0, n3(vec3(vWPos.x * 1.5, vWPos.y * 90.0, vWPos.z * 1.5)));
roughnessFactor = clamp(roughnessFactor + (nz - 0.5) * 0.06 + scr * 0.05, 0.04, 1.0);`)
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
float band = (vWPos.x * 0.8 + vWPos.y * 0.6) - uSweep;
totalEmissiveRadiance += vec3(1.0, 0.86, 0.6) * uSweepGain * exp(-band * band * 18.0);`);
  };
  m.customProgramCacheKey = () => 'gold';
  return m;
}

const MAT_POLISH = goldMaterial(0.13);
const MAT_SATIN = goldMaterial(0.36);
const LOGO_SWEEP = { value: -9.0 };
const LOGO_GAIN = { value: 0.0 };
const MAT_LOGO = goldMaterial(0.11, { clearcoat: 0.0 });
MAT_LOGO.userData.sweep = LOGO_SWEEP;
MAT_LOGO.userData.sweepGain = LOGO_GAIN;

// ══════════════════════════════ المجسّمات
async function loadGLB(b64) {
  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  await MeshoptDecoder.ready;
  return new Promise((res, rej) => loader.parse(b64buf(b64), '', res, rej));
}

function goldify(root, logo = false) {
  root.traverse((o) => {
    if (!o.isMesh) return;
    const n = (o.material && o.material.name) || '';
    o.material = logo ? MAT_LOGO : (n.indexOf('Satin') >= 0 ? MAT_SATIN : MAT_POLISH);
    o.castShadow = !logo;
    o.receiveShadow = !logo;
  });
  return root;
}

function find(root, name) {
  let hit = null;
  root.traverse((o) => { if (!hit && o.name && o.name.indexOf(name) === 0) hit = o; });
  return hit;
}

function placed(src, x, y, z, yaw, flip = false) {
  const g = new THREE.Group();
  const m = src.clone();
  m.position.set(0, 0, 0);
  g.add(m);
  g.position.set(x, y, z);
  g.rotation.set(flip ? Math.PI : 0, yaw, 0);
  return g;
}

// ══════════════════════════════ الأرض: أسودٌ لامع بانعكاسٍ حقيقي
function glossyFloor(w, h) {
  const shader = {
    name: 'GlossyFloor',
    uniforms: {
      color: { value: null }, tDiffuse: { value: null }, textureMatrix: { value: null },
      uStrength: { value: 1.25 }, uFade: { value: 7.5 }, uTexel: { value: new THREE.Vector2(1 / 1024, 1 / 512) },
      uPool: { value: new THREE.Vector3(-0.2, 0.4, 2.2) },
    },
    vertexShader: /* glsl */`
      uniform mat4 textureMatrix; varying vec4 vUv; varying vec3 vW;
      void main(){ vUv = textureMatrix * vec4(position, 1.0); vW = (modelMatrix * vec4(position, 1.0)).xyz;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */`
      uniform sampler2D tDiffuse; uniform float uStrength; uniform float uFade; uniform vec2 uTexel; uniform vec3 uPool;
      varying vec4 vUv; varying vec3 vW;
      float hh(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
      void main(){
        vec2 uv = vUv.xy / vUv.w;
        // نعومة اللكّ: عيّناتٌ دائرية تتّسع قليلاً مع البعد عن مركز المشهد
        float r = length(vW.xz);
        float rad = 0.8 + r * 0.42;
        vec3 acc = texture2D(tDiffuse, uv).rgb * 0.22;
        float wsum = 0.22;
        for (int i = 0; i < 10; i++) {
          float a = float(i) * 2.39996 + hh(gl_FragCoord.xy) * 0.6;
          float d = sqrt((float(i) + 0.5) / 10.0) * rad;
          vec2 o = vec2(cos(a), sin(a)) * d * uTexel * 2.0;
          float wt = 1.0 - float(i) / 12.0;
          acc += texture2D(tDiffuse, uv + o).rgb * wt; wsum += wt;
        }
        vec3 refl = acc / wsum;
        float fade = smoothstep(uFade, 0.0, r);
        // فرنل اللكّ الأسود: انعكاسٌ خافت إذا نظرنا من فوق، ويقوى كلما مالت النظرة
        float ct = clamp(normalize(cameraPosition - vW).y, 0.0, 1.0);
        float fr = 0.045 + 0.955 * pow(1.0 - ct, 5.0);
        vec3 col = refl * uStrength * fr * fade;
        // بقعةُ ضوءٍ دافئة خافتة تحت الذهب، وسوادٌ عميق حولها
        vec2 pp = vW.xz - uPool.xy;
        col += vec3(0.055, 0.035, 0.016) * exp(-dot(pp, pp) / (uPool.z * uPool.z));
        col += vec3(0.004, 0.0032, 0.0026);
        gl_FragColor = vec4(col, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  };
  const f = new Reflector(new THREE.PlaneGeometry(w, h), {
    shader, clipBias: 0.002, color: 0xffffff,
    textureWidth: 1024, textureHeight: 512, multisample: 0,
  });
  f.rotation.x = -Math.PI / 2;
  return f;
}

// ══════════════════════════════ الخلفية: ليلٌ دافئ بضوءٍ منسكب
function backdrop() {
  const m = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false,
    uniforms: { uTime: { value: 0 } },
    vertexShader: `varying vec3 vD; void main(){ vD = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying vec3 vD; uniform float uTime;
      float hh(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
      void main(){
        vec3 d = normalize(vD);
        float up = clamp(d.y * 0.5 + 0.5, 0.0, 1.0);
        vec3 c = mix(vec3(0.002, 0.0016, 0.0012), vec3(0.016, 0.011, 0.006), smoothstep(0.35, 1.0, up));
        // انسكابُ ضوءٍ دافئ أعلى اليسار — كما في استوديو التصوير
        vec3 key = normalize(vec3(-0.75, 0.55, -0.35));
        c += vec3(0.11, 0.07, 0.03) * pow(max(dot(d, key), 0.0), 6.0);
        c += (hh(gl_FragCoord.xy + uTime) - 0.5) * 0.0025;     // لا تدرّج متدرّج
        gl_FragColor = vec4(c, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  return new THREE.Mesh(new THREE.SphereGeometry(80, 48, 24), m);
}

// ══════════════════════════════ غبار الذهب
function dust(n, spread, near = false) {
  const g = new THREE.BufferGeometry();
  const p = new Float32Array(n * 3), s = new Float32Array(n * 4);
  for (let i = 0; i < n; i++) {
    p[i * 3] = (Math.random() - 0.5) * spread.x;
    p[i * 3 + 1] = Math.random() * spread.y;
    p[i * 3 + 2] = (Math.random() - 0.5) * spread.z;
    s[i * 4] = Math.random(); s[i * 4 + 1] = Math.random();
    s[i * 4 + 2] = 0.4 + Math.random() * 0.6; s[i * 4 + 3] = Math.random();
  }
  g.setAttribute('position', new THREE.BufferAttribute(p, 3));
  g.setAttribute('seed', new THREE.BufferAttribute(s, 4));
  const m = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 }, uPx: { value: 1 }, uSize: { value: near ? 46.0 : 5.2 },
      uH: { value: spread.y }, uGain: { value: 0 }, uBeam: { value: new THREE.Vector3(-0.62, 0.78, 0.1).normalize() },
    },
    vertexShader: `attribute vec4 seed; uniform float uTime; uniform float uPx; uniform float uSize; uniform float uH; uniform vec3 uBeam;
      varying float vA; varying float vTw;
      void main(){
        vec3 q = position;
        float t = uTime * (0.05 + seed.x * 0.07);
        q.y = mod(q.y + t * 2.0, uH);
        q.x += sin(uTime * 0.21 + seed.y * 6.28) * 0.35 + sin(q.y * 0.7 + seed.w * 6.28) * 0.25;
        q.z += cos(uTime * 0.17 + seed.x * 6.28) * 0.35;
        vec4 mv = modelViewMatrix * vec4(q, 1.0);
        gl_Position = projectionMatrix * mv;
        gl_PointSize = uSize * seed.z * uPx * (8.0 / -mv.z);
        vTw = 0.55 + 0.45 * sin(uTime * (0.8 + seed.w * 2.0) + seed.y * 40.0);
        // أسطع في شعاع الضوء المائل وأخفت عند الحوافّ العليا والسفلى
        float inBeam = smoothstep(0.55, 0.0, length(cross(normalize(q - vec3(-3.4, 6.5, 0.6)), uBeam)));
        vA = (0.35 + inBeam * 0.9) * smoothstep(0.0, 0.8, q.y) * smoothstep(uH, uH * 0.7, q.y);
      }`,
    fragmentShader: `uniform float uGain; varying float vA; varying float vTw;
      void main(){ vec2 c = gl_PointCoord - 0.5; float r = dot(c, c) * 4.0;
        float a = exp(-r * 3.2) * vA * vTw * uGain; if (a < 0.003) discard;
        gl_FragColor = vec4(vec3(1.0, 0.74, 0.36) * a * 1.6, a); }`,
  });
  return new THREE.Points(g, m);
}

// ══════════════════════════════ شعاع الضوء
function beam() {
  const geo = new THREE.CylinderGeometry(0.25, 2.6, 11, 48, 1, true);
  geo.translate(0, -5.5, 0);
  const m = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    uniforms: { uTime: { value: 0 }, uGain: { value: 0 } },
    vertexShader: `varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){ vUv = uv; vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position, 1.0); vV = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `uniform float uTime; uniform float uGain; varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      float hh(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
      float nn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
        return mix(mix(hh(i), hh(i + vec2(1, 0)), f.x), mix(hh(i + vec2(0, 1)), hh(i + vec2(1, 1)), f.x), f.y); }
      void main(){
        float edge = pow(abs(dot(normalize(vN), normalize(vV))), 2.2);
        float along = smoothstep(0.0, 0.25, vUv.y) * smoothstep(1.0, 0.55, vUv.y);
        float dustN = 0.75 + 0.25 * nn(vec2(vUv.x * 18.0, vUv.y * 4.0 - uTime * 0.08));
        float a = edge * along * dustN * 0.05 * uGain;
        gl_FragColor = vec4(vec3(1.0, 0.82, 0.55) * a, a);
      }`,
  });
  const mesh = new THREE.Mesh(geo, m);
  mesh.position.set(-3.4, 6.6, 0.6);
  mesh.lookAt(new THREE.Vector3(0.0, 0.0, 0.2));
  mesh.rotateX(Math.PI / 2);
  return mesh;
}

// ══════════════════════════════ التلوين النهائي (بعد تحويل الألوان)
const GradeShader = {
  uniforms: { tDiffuse: { value: null }, uTime: { value: 0 }, uVig: { value: 0.42 }, uDark: { value: 0 } },
  vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: `uniform sampler2D tDiffuse; uniform float uTime; uniform float uVig; uniform float uDark; varying vec2 vUv;
    float hh(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
    void main(){
      vec2 c = vUv - 0.5;
      float r2 = dot(c, c);
      // زيغٌ لونيٌّ خفيف عند الأطراف — كعدسةٍ حقيقية
      vec2 off = c * r2 * 0.006;
      vec3 col = vec3(texture2D(tDiffuse, vUv + off).r, texture2D(tDiffuse, vUv).g, texture2D(tDiffuse, vUv - off).b);
      col *= mix(1.0, smoothstep(0.85, 0.12, r2 * 1.9), uVig);
      col = mix(col, col * vec3(1.03, 1.0, 0.95), 0.6);
      col += (hh(vUv * 1937.0 + fract(uTime * 7.31)) - 0.5) * 0.022;   // حبيبٌ سينمائي
      col *= (1.0 - uDark);
      gl_FragColor = vec4(col, 1.0);
    }`,
};

// ══════════════════════════════ التركيب
const camera = new THREE.PerspectiveCamera(26, 16 / 9, 0.1, 200);
const logoCam = new THREE.PerspectiveCamera(18, 16 / 9, 0.1, 50);
const rig = { az: -0.62, el: 0.10, dist: 19.5, tx: 0.0, ty: 0.45, tz: 0.55, shift: 0.225 };
const logoRect = { cx: 0, cy: 0, w: 0, h: 0, on: false };
let W = 1, H = 1;
let composer, bloom, grade, floor, dustFar, dustNear, beamMesh, logoGroup, logoParts = [];
let key, rim, fill;
let running = false, last = 0, clock = 0, exitK = 0, intro = null;
const perf = { frames: 0, acc: 0, tier: 2, checked: false };

function placeCamera() {
  const ce = Math.cos(rig.el);
  camera.position.set(rig.tx + rig.dist * ce * Math.sin(rig.az), rig.ty + rig.dist * Math.sin(rig.el),
    rig.tz + rig.dist * ce * Math.cos(rig.az));
  camera.lookAt(rig.tx, rig.ty, rig.tz);
  // إزاحة العدسة: السبائك في يسار الكادر، والمنظور طبيعيٌّ كما هو
  camera.setViewOffset(W, H, W * rig.shift, 0, W, H);
}

function placeLogo() {
  if (!logoGroup) return;
  const on = logoRect.on && logoRect.w > 8;
  logoGroup.visible = on;
  if (!on) return;
  // الشعار بعرض المستطيل المطلوب في موضعه بالضبط: الكاميرا تنظر إلى مركزه،
  // وإزاحة العدسة تضعه حيث يقول البرنامج
  const fov = THREE.MathUtils.degToRad(logoCam.fov);
  const wantH = logoRect.h;                                  // بكسلات
  const unitsH = logoGroup.userData.h || 3.0;
  const dist = (unitsH / 2) / Math.tan(fov / 2) * (H / wantH);
  logoCam.position.set(0, 0, dist);
  logoCam.lookAt(0, 0, 0);
  logoCam.aspect = W / H;
  logoCam.setViewOffset(W, H, W / 2 - logoRect.cx, H / 2 - logoRect.cy, W, H);
  logoCam.updateProjectionMatrix();
}

function resize() {
  W = Math.max(2, window.innerWidth);
  H = Math.max(2, window.innerHeight);
  renderer.setSize(W, H, false);
  camera.aspect = W / H;
  placeCamera();
  camera.updateProjectionMatrix();
  if (composer) {
    composer.setPixelRatio(PR);
    composer.setSize(W, H);
  }
  if (floor) floor.material.uniforms.uTexel.value.set(1 / (W * 0.5), 1 / (H * 0.5));
  if (dustFar) { dustFar.material.uniforms.uPx.value = PR * H / 1080; dustNear.material.uniforms.uPx.value = PR * H / 1080; }
  placeLogo();
}

async function build() {
  const env = studioEnvironment();
  scene.environment = env;
  logoScene.environment = env;
  scene.add(backdrop());

  // الضوء الرئيسي: كشّافٌ أعلى اليسار بظلالٍ ناعمة، وحافّةٌ دافئة خلفية
  key = new THREE.SpotLight(0xfff1dc, 0, 40, THREE.MathUtils.degToRad(24), 0.65, 2);
  key.position.set(-4.2, 8.5, 4.5);
  key.target.position.set(0, 0.4, 0);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.bias = -0.0002;
  key.shadow.normalBias = 0.02;
  key.shadow.radius = 6;
  key.shadow.camera.near = 4; key.shadow.camera.far = 20;
  scene.add(key, key.target);
  rim = new THREE.SpotLight(0xffd59a, 0, 40, THREE.MathUtils.degToRad(30), 0.8, 2);
  rim.position.set(5.5, 3.2, -6.5);
  rim.target.position.set(0, 0.5, 0);
  scene.add(rim, rim.target);
  fill = new THREE.HemisphereLight(0x2a1d10, 0x000000, 0.0);
  scene.add(fill);

  floor = glossyFloor(70, 70);
  scene.add(floor);
  // ظلّ التماس: طبقةٌ لا ترى إلا الظلّ، فوق المرآة بقليل
  const shadowCatcher = new THREE.Mesh(new THREE.PlaneGeometry(30, 30),
    new THREE.ShadowMaterial({ opacity: 0.72, color: 0x000000 }));
  shadowCatcher.rotation.x = -Math.PI / 2;
  shadowCatcher.position.y = 0.002;
  shadowCatcher.receiveShadow = true;
  scene.add(shadowCatcher);

  // السبائك (طولها على x، وعرضها على z، وقاعدتها على الأرض):
  // هرمٌ كما تُرصّ في الخزائن — ثلاثٌ، فوقها اثنتان مقلوبتان (الوجه العريض
  // للأعلى)، فواحدةٌ في القمّة يظهر ختمها — وسبيكة سكٍّ مسنودةٌ إلى الرصّة،
  // وسبيكةٌ وسبيكتا سكٍّ ملقاةٌ أمامها
  const bars = goldify((await loadGLB(DATA.bars)).scene);
  const cast = find(bars, 'BarCast'), mint = find(bars, 'BarMint');
  const H0 = 0.50, G = 1.13;
  const stack = new THREE.Group();
  stack.add(
    placed(cast, 0, 0, -G, 0), placed(cast, 0, 0, 0, 0), placed(cast, 0, 0, G, 0),
    placed(cast, 0.03, H0 * 2, -G / 2, 0, true), placed(cast, -0.02, H0 * 2, G / 2, 0, true),
    placed(cast, 0.01, H0 * 2, 0, 0.012),
  );
  // سبيكة سكٍّ مسنودة: حافّتها العليا على حافّة السبيكة الأمامية
  const lean = placed(mint, 0, 0, 0, 0);
  const th = 1.13;                                         // ميلها عن الأرض
  lean.rotation.set(th, 0, 0);
  const low = new THREE.Vector3(0, 0, 0.29).applyEuler(lean.rotation);
  lean.position.set(0.42, -low.y + 0.001, 0);
  // ظهرها يلامس حافّة السبيكة السفلى الأمامية (ارتفاع H0، وعمق G + 0.40)
  const zc = (lean.position.y - H0) / Math.sin(th);
  lean.position.z = G + 0.404 - zc * Math.cos(th);
  stack.add(lean);
  stack.rotation.y = 0.52;
  stack.position.set(-0.55, 0, -0.7);
  scene.add(stack);
  [
    placed(cast, 1.55, 0, 1.55, -0.28),
    placed(mint, -1.95, 0, 1.75, 0.38),
    placed(mint, -0.15, 0, 2.55, -0.16),
  ].forEach((b) => scene.add(b));

  dustFar = dust(1400, new THREE.Vector3(16, 7.5, 12));
  dustNear = dust(70, new THREE.Vector3(10, 6, 5), true);
  dustNear.position.z = 5.5;
  scene.add(dustFar, dustNear);
  beamMesh = beam();
  scene.add(beamMesh);

  // الشعار في مشهده: الرمز فوق، فالاسم، فالسطر العربي — كما في الهوية
  const logo = goldify((await loadGLB(DATA.logo)).scene, true);
  logoGroup = new THREE.Group();
  logoGroup.add(logo);
  const box = new THREE.Box3().setFromObject(logo);
  const c = box.getCenter(new THREE.Vector3());
  logo.position.sub(c);
  logoGroup.userData.h = box.max.y - box.min.y;
  logoParts = ['LogoEmblem', 'LogoName', 'LogoTagline'].map((n) => find(logo, n)).filter(Boolean);
  logoScene.add(logoGroup);
  const lk = new THREE.DirectionalLight(0xfff0d8, 1.6);
  lk.position.set(-2, 3, 5);
  logoScene.add(lk);

  composer = new EffectComposer(renderer, new THREE.WebGLRenderTarget(2, 2, {
    type: THREE.HalfFloatType, samples: 4,
  }));
  composer.addPass(new RenderPass(scene, camera));
  const lp = new RenderPass(logoScene, logoCam);
  lp.clear = false;
  lp.clearDepth = true;
  composer.addPass(lp);
  // التوهّج للّمعات الحادّة وحدها (عتبةٌ فوق الأبيض)، لا ضبابٌ على المشهد
  bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.24, 0.36, 1.6);
  composer.addPass(bloom);
  bloom.enabled = !OFF.has('bloom');
  beamMesh.visible = !OFF.has('beam');
  floor.visible = !OFF.has('floor');
  key.visible = !OFF.has('key');
  rim.visible = !OFF.has('rim');
  if (OFF.has('env')) { scene.environment = null; }
  composer.addPass(new OutputPass());
  grade = new ShaderPass(GradeShader);
  composer.addPass(grade);
  resize();
}

// ══════════════════════════════ الحركة (GSAP)
const L = { key: 0, rim: 0, dust: 0, beam: 0, logoK: 0, logoRot: -1.15, exposure: 0 };

function timeline() {
  const tl = gsap.timeline({ paused: true });
  // ١) من العتمة: الضوء يشتعل والكاميرا تقترب منخفضةً ثم ترتفع قليلاً
  tl.to(L, { exposure: 1.0, duration: 2.6, ease: 'power2.out' }, 0);
  tl.to(L, { key: 95, duration: 2.2, ease: 'power2.inOut' }, 0.15);
  tl.to(L, { rim: 90, duration: 2.6, ease: 'power2.out' }, 0.6);
  tl.to(rig, { dist: 13.6, el: 0.21, az: -0.30, duration: 5.2, ease: 'power3.out' }, 0);
  tl.to(L, { dust: 1, beam: 1, duration: 3.0, ease: 'sine.inOut' }, 0.9);
  // ٢) الشعار: يستدير إلى الأمام وهو يخرج من العتمة، ثم تعبره لمعة
  tl.to(L, { logoK: 1, duration: 2.2, ease: 'power2.out' }, 0.5);
  tl.to(L, { logoRot: 0, duration: 2.6, ease: 'power3.out' }, 0.5);
  tl.fromTo(LOGO_SWEEP, { value: -3.2 }, { value: 3.2, duration: 1.7, ease: 'power1.inOut' }, 2.5);
  tl.fromTo(LOGO_GAIN, { value: 0 }, { value: 1.6, duration: 0.5, yoyo: true, repeat: 1, ease: 'sine.inOut' }, 2.6);
  return tl;
}

function idle() {
  // ٣) دورانٌ بطيءٌ حول السبائك ذهاباً وإياباً، وتنفّسٌ في البعد والارتفاع
  gsap.to(rig, { az: 0.16, duration: 24, ease: 'sine.inOut', yoyo: true, repeat: -1 });
  gsap.to(rig, { dist: 12.9, el: 0.245, duration: 15, ease: 'sine.inOut', yoyo: true, repeat: -1 });
  // الكشّاف الرئيسي يتمايل ببطء: لمعته تنزلق على الحوافّ المشطوفة والظلال
  // تتحرّك قليلاً — كضوء استوديو يُحرَّك أثناء التصوير
  gsap.to(key.position, { x: -2.2, z: 5.6, duration: 11, ease: 'sine.inOut', yoyo: true, repeat: -1 });
  // لمعةٌ تعبر الشعار كل بضع ثوانٍ
  const sweep = () => {
    gsap.fromTo(LOGO_SWEEP, { value: -3.2 }, { value: 3.2, duration: 1.8, ease: 'power1.inOut' });
    gsap.fromTo(LOGO_GAIN, { value: 0 }, { value: 1.2, duration: 0.6, yoyo: true, repeat: 1, ease: 'sine.inOut' });
  };
  gsap.delayedCall(7, function loop() { sweep(); gsap.delayedCall(9, loop); });
}

function apply(t) {
  renderer.toneMappingExposure = L.exposure * (1 - exitK * 0.85);
  key.intensity = L.key;
  rim.intensity = L.rim;
  fill.intensity = 0.25 * L.exposure;
  dustFar.material.uniforms.uGain.value = L.dust;
  dustNear.material.uniforms.uGain.value = L.dust * 0.55;
  beamMesh.material.uniforms.uGain.value = L.beam;
  for (const m of [dustFar, dustNear, beamMesh]) m.material.uniforms.uTime.value = t;
  grade.uniforms.uTime.value = t;
  grade.uniforms.uDark.value = exitK * 0.55;
  if (logoGroup) {
    MAT_LOGO.envMapIntensity = 0.15 + 0.95 * L.logoK;
    logoGroup.rotation.y = L.logoRot + Math.sin(t * 0.35) * 0.06 * L.logoK;
    logoGroup.rotation.x = Math.sin(t * 0.27) * 0.025;
    logoGroup.position.y = (1 - L.logoK) * -0.25;
    const s = 0.9 + 0.1 * L.logoK;
    logoGroup.scale.setScalar(s);
    logoGroup.visible = logoRect.on && logoRect.w > 8 && (L.logoK > 0.01 || STILL);
  }
  // الخروج: الكاميرا تتقدّم والمشهد يعتم
  const d0 = rig.dist;
  rig.dist = d0 * (1 - exitK * 0.22);
  placeCamera();
  rig.dist = d0;
}

function frame(now) {
  if (!running) return;
  requestAnimationFrame(frame);
  const dt = last ? Math.min(0.1, (now - last) / 1000) : 0.016;
  last = now;
  clock += dt;
  apply(clock);
  composer.render(dt);
  if (!perf.checked) tune(dt);
  if (perf.frames === 3 && !perf.ready) { perf.ready = true; say('ready ' + GPU); }
}

function tune(dt) {
  // جهازٌ أبطأ: دقّةٌ أقل ثم توهّجٌ أخفّ — لا مشهدٌ يتقطّع
  perf.frames++;
  if (perf.frames < 30) return;
  perf.acc += dt;
  if (perf.frames < 90) return;
  const ms = perf.acc / 60 * 1000;
  perf.acc = 0; perf.frames = 30;
  if (ms > 24 && perf.tier > 0) {
    perf.tier--;
    if (perf.tier === 1) { PR = Math.max(0.75, PR * 0.75); }
    else { PR = Math.max(0.6, PR * 0.8); bloom.enabled = false; dustFar.geometry.setDrawRange(0, 700); }
    resize();
    say('tier ' + perf.tier + ' ' + ms.toFixed(1) + 'ms');
  } else {
    perf.checked = true;
    say('fps ' + (1000 / ms).toFixed(0));
  }
}

// ══════════════════════════════ الصلة بالبرنامج
window.gate3d = {
  start() {
    if (running) return;
    running = true;
    last = 0;
    if (!intro) { intro = timeline(); intro.eventCallback('onComplete', idle); intro.play(); }
    requestAnimationFrame(frame);
  },
  pause() { running = false; gsap.globalTimeline.pause(); },
  resume() { if (!running) { gsap.globalTimeline.resume(); this.start(); } },
  setLogoRect(cx, cy, w, h) {
    Object.assign(logoRect, { cx, cy, w, h, on: true });
    placeLogo();
  },
  hideLogo() { logoRect.on = false; placeLogo(); },
  setExit(v) { exitK = Math.max(0, Math.min(1, Number(v) || 0)); },
  info() { return { tier: perf.tier, pr: PR, w: W, h: H }; },
};

window.addEventListener('resize', resize);
window.addEventListener('error', (e) => say('error ' + (e.message || e)));

build().then(() => {
  say('built');
  if (STILL) {
    // لقطةٌ ثابتة عند ثانيةٍ بعينها (للاختبار والصور)
    const tl = timeline();
    tl.seek(Math.min(T0, tl.duration()));
    if (T0 > tl.duration()) { rig.az = -0.30 + Math.sin((T0 - tl.duration()) / 24 * Math.PI) * 0.46; }
    if (Q.has('cam')) {   // كاميرا للفحص: az,el,dist,tx,ty,tz,shift
      const [az, el, dist, tx, ty, tz, shift] = Q.get('cam').split(',').map(Number);
      Object.assign(rig, { az, el, dist, tx, ty, tz, shift });
    }
    if (Q.has('logo')) {
      const [cx, cy, w, h] = Q.get('logo').split(',').map(Number);
      window.gate3d.setLogoRect(cx, cy, w, h);
    }
    for (let i = 0; i < 3; i++) { apply(T0); composer.render(0.016); }
    say('still');
    return;
  }
  if (Q.has('logo')) {
    const [cx, cy, w, h] = Q.get('logo').split(',').map(Number);
    window.gate3d.setLogoRect(cx, cy, w, h);
  }
  if (Q.has('autostart')) window.gate3d.start();
}).catch((e) => say('fail ' + (e && (e.stack || e.message) || e)));
