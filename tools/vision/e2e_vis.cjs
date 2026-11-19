// تجربة «البحث بالصورة» في متصفّحٍ حقيقي (Chromium) على خادم البرنامج نفسه.
//
//   node tools/vision/e2e_vis.cjs <ملف-الإعداد.json> <مجلد-المجموعة> [عدد اللقطات] [--mobile]
//
// 1) تُفتح صفحة /vis: تُنتظر الحزمة والنموذج، ويُبنى فهرس الدليل ويُحفظ.
// 2) تُعاد الصفحة: يُقرأ الفهرس من جهاز المصنع (لا يُحسب ثانيةً).
// 3) تُرفع لقطات «الجوال»: الطقم الصحيح في المرتبة الأولى أو بين الخمسة الأوائل.
// 4) لقطةٌ ثانية للطقم نفسه تُدمج مع الأولى.
const fs = require('fs');
const path = require('path');
const { chromium, devices } = require('playwright');

(async () => {
  const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const bench = process.argv[3];
  const limit = +(process.argv[4] || 0) || 1e9;
  const mobile = process.argv.includes('--mobile');
  const photos = JSON.parse(fs.readFileSync(path.join(bench, 'photos.json'), 'utf8')).slice(0, limit);
  const OK = [], BAD = [];
  const check = (n, c, info) => { (c ? OK : BAD).push(n); console.log((c ? '  ✔ ' : '  ✘ ') + n + (c ? '' : '  [' + (info || '') + ']')); };

  const b = await chromium.launch();
  const ctx = await b.newContext(mobile ? { ...devices['Pixel 7'] } : { viewport: { width: 420, height: 900 } });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push(String(e)));
  p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });

  console.log('── 1) فتح الصفحة وبناء الفهرس');
  let t0 = Date.now();
  await p.goto(cfg.url + '/vis');
  check('الصفحة معزولة (crossOriginIsolated) فيعمل المحرّك بأنوية', await p.evaluate(() => self.crossOriginIsolated));
  await p.waitForFunction(() => window.__visReady === true || !document.getElementById('err').hidden, null, { timeout: 30 * 60 * 1000, polling: 1000 });
  const errTxt = await p.evaluate(() => document.getElementById('err').hidden ? '' : document.getElementById('err').textContent);
  check('جاهز بلا خطأ', !errTxt, errTxt);
  const nIdx = await p.evaluate(() => Object.keys(window.__vis.idx).length);
  const nCat = await p.evaluate(() => JSON.parse(document.getElementById('vis-data').textContent).catalog.length);
  const t1 = Date.now();
  check(`فُهرس الدليل كله (${nIdx}/${nCat}) في ${Math.round((t1 - t0) / 1000)} ث`, nIdx === nCat && nCat > 0);

  console.log('── 2) إعادة فتح الصفحة: الفهرس من جهاز المصنع');
  t0 = Date.now();
  await p.reload();
  await p.waitForFunction(() => window.__visReady === true, null, { timeout: 120000 });
  const t2 = Date.now() - t0;
  const nIdx2 = await p.evaluate(() => Object.keys(window.__vis.idx).length);
  check(`الفهرس قُرئ محفوظاً (${nIdx2}) وجاهزٌ في ${(t2 / 1000).toFixed(1)} ث`, nIdx2 === nCat && t2 < 60000, t2);

  console.log('── 3) البحث بلقطات «الجوال»');
  const ranks = [], kinds = [];
  let ts = 0;
  for (const ph of photos) {
    const s0 = Date.now();
    await p.setInputFiles('#gal', path.join(bench, 'photos', ph.file));
    await p.waitForSelector('#crop:not([hidden])');
    await p.click('#full');
    await p.waitForSelector('#res:not([hidden]) .hit');
    ts += Date.now() - s0;
    const names = await p.$$eval('.hit h2 span:first-child', els => els.map(e => e.textContent.replace('الموديل ', '').trim()));
    const all = await p.evaluate(() => window.__vis.rank().map(r => r.c.m));
    const r = all.indexOf(ph.id) + 1;
    ranks.push(r || 999); kinds.push(ph.kind);
    if (names[0] !== all[0]) BAD.push('ترتيب العرض يطابق الترتيب');
  }
  const st = (sel) => {
    const rr = ranks.filter((_, i) => sel(kinds[i]));
    const f = k => (100 * rr.filter(x => x <= k).length / Math.max(1, rr.length)).toFixed(1);
    return { n: rr.length, top1: f(1), top3: f(3), top5: f(5), top10: f(10) };
  };
  const A = st(() => true), S = st(k => k === 'set'), P = st(k => k !== 'set');
  console.log('   الكل ', JSON.stringify(A));
  console.log('   طقم  ', JSON.stringify(S));
  console.log('   قطعة ', JSON.stringify(P));
  console.log(`   متوسط زمن البحث للّقطة: ${Math.round(ts / Math.max(1, photos.length))} م.ث`);
  // حرّاسٌ من التراجع (القيم المقيسة: الكل 78/91 · الطقم 88/96 بين الخمسة/العشرة)
  check('الكل: الصحيح بين العشرة الأوائل ≥ 85%', +A.top10 >= 85, A.top10);
  check('الطقم كاملاً: الصحيح بين الخمسة الأوائل ≥ 80%', +S.top5 >= 80, S.top5);
  check('الطقم كاملاً: الصحيح بين العشرة الأوائل ≥ 90%', +S.top10 >= 90, S.top10);

  console.log('── 4) لقطةٌ ثانية للطقم نفسه تُدمج');
  const two = photos.filter(x => x.kind === 'set').slice(0, 2);
  if (two.length === 2 && two[0].id === two[1].id) {
    await p.setInputFiles('#gal', path.join(bench, 'photos', two[0].file));
    await p.click('#full');
    await p.waitForSelector('#res:not([hidden]) .hit');
    await p.setInputFiles('#add', path.join(bench, 'photos', two[1].file));
    await p.click('#full');
    await p.waitForFunction(() => /من 2 لقطات/.test(document.getElementById('rS').textContent));
    check('«من 2 لقطات» — والدمج يعمل', true);
  }
  const shot = path.join(path.dirname(process.argv[2]), 'vis_result.png');
  await p.screenshot({ path: shot, fullPage: false });
  check('بلا أخطاء في الصفحة', errs.length === 0, errs.slice(0, 3).join(' | '));
  console.log(`\n${OK.length} ✔ · ${BAD.length} ✘`);
  fs.writeFileSync(path.join(path.dirname(process.argv[2]), 'vis_ranks.json'), JSON.stringify({ ranks, kinds, photos }, null, 1));
  await b.close();
  process.exit(BAD.length ? 1 : 0);
})();
