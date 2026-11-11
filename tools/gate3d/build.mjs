// يجمع مشهد بوابة الدخول ثلاثي الأبعاد للبرنامج — ملفّاتٌ محلّية لا تحتاج الإنترنت.
//
//   cd tools/gate3d && npm ci && node build.mjs
//
// ① يضغط مجسّمات Blender الخام (build/*.glb من make_models.py) بـ gltfpack
//    (meshopt) — أصغر بأربع مرّات تقريباً بلا فرقٍ يُرى.
// ② يجمع three.js وGSAP والمشهد (src/main.js) في ملفٍ واحد: assets/gate3d/gate3d.js
// ③ يضع المجسّمات المضغوطة نصّاً (base64) في assets/gate3d/data.js — صفحة
//    البرنامج تُفتح من القرص، والمتصفّح المدمج لا يقرأ الملفّات بـ fetch.
//    (صورة الإضاءة من Poly Haven — CC0 — مضمّنةٌ في gate3d.js نفسه.)
import { build } from 'esbuild';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync, mkdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, '..', '..', 'assets', 'gate3d');
const RAW = join(HERE, 'build');
mkdirSync(OUT, { recursive: true });

const kb = (p) => (statSync(p).size / 1024).toFixed(0) + ' KB';
const pack = (name) => {
  const src = join(RAW, name + '.glb');
  const dst = join(RAW, name + '.pack.glb');
  if (!existsSync(src)) throw new Error('missing ' + src + ' — run make_models.py first');
  // -cc: ضغط meshopt · -kn/-km: الأسماء والمواد تبقى (المشهد يقرأها)
  // -vp 16 / -vn 10: دقّة المواقع والاتجاهات — حوافّ الختم تبقى حادّة
  execFileSync(join(HERE, 'node_modules', '.bin', 'gltfpack'),
    ['-i', src, '-o', dst, '-cc', '-kn', '-km', '-vp', '16', '-vn', '10'], { stdio: 'inherit' });
  console.log('  ' + name + ': ' + kb(src) + ' → ' + kb(dst));
  return 'data:model/gltf-binary;base64,' + readFileSync(dst).toString('base64');
};

const data = { bars: pack('bars'), logo: pack('logo') };
writeFileSync(join(OUT, 'data.js'),
  '// مجسّمات المشهد (مولَّدة بـ tools/gate3d/build.mjs — لا تُعدَّل يدوياً)\n'
  + 'window.GATE3D_DATA=' + JSON.stringify(data) + ';\n');

await build({
  entryPoints: [join(HERE, 'src', 'main.js')],
  bundle: true, format: 'iife', minify: true, target: ['chrome80'],
  outfile: join(OUT, 'gate3d.js'), legalComments: 'eof', logLevel: 'warning',
  // three/addons/* → three/examples/jsm/* (كما في خريطة الاستيراد الرسمية)
  alias: { 'three/addons': 'three/examples/jsm' },
});
console.log('  gate3d.js: ' + kb(join(OUT, 'gate3d.js')) + ' · data.js: ' + kb(join(OUT, 'data.js')));
