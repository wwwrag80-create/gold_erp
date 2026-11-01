// فيديو تعليمي — الخطوة 2: المسرح إطاراً إطاراً ← MP4 (H.264، 1080×1920).
//   node mobile/tools/video/render.js SHOTS_DIR OUT.mp4 [--preview 3,12.5,...] [--fps 30] [--jobs 3]
// يقرأ manifest.json من capture.js، ويبني الخطّ الزمني (timeline.json — يقرؤه
// music.py للمؤثرات)، ويرسم كل إطارٍ في Chromium بـ renderAt(t) ثم يلتقطه.
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const { chromium } = require("playwright");

const args = process.argv.slice(2);
const SHOTS = path.resolve(args[0] || "video-shots");
const OUT = path.resolve(args[1] || "tutorial.mp4");
const opt = (k, d) => { const i = args.indexOf("--" + k); return i >= 0 ? args[i + 1] : d; };
const FPS = Number(opt("fps", 30));
const JOBS = Number(opt("jobs", 3));
const PREVIEW = opt("preview", "");

const SC = 517 / 393;   // نقاط الشاشة ← بكسل شاشة الجوال في المسرح
function timeline(m) {
  const segs = [];
  let t = 0;
  const add = (o, d) => { segs.push(Object.assign(o, { start: +t.toFixed(3), end: +(t + d).toFixed(3) })); t += d; };
  add({ type: "intro" }, 5.0);
  const items = m.shots;
  const chapters = items.filter((x) => x.type === "chapter");
  let ch = null, step = 0, prevIdx = null, idx = 0;
  items.forEach((it, i) => {
    if (it.type === "chapter") { ch = it; step = 0; prevIdx = null; add({ type: "chapter", n: it.n, title: it.title, desc: it.desc }, 2.4); return; }
    step++;
    const steps = items.filter((x) => x.type === "shot" && x.chapter === it.chapter).length;
    const len = (it.title + " " + it.sub).length;
    let d = Math.min(5.6, Math.max(3.2, 2.2 + 0.038 * len));
    if (it.tap) d += 0.85;
    const next = items[i + 1];
    add({ type: "shot", idx, file: "file://" + path.join(SHOTS, it.file), title: it.title, sub: it.sub, tap: it.tap,
      tapAt: it.tap ? +(d - 0.9).toFixed(3) : null,
      // تقريبٌ هادئ بعد لحظةٍ من ظهور الشاشة كاملة، ثم إبعادٌ قبل الانتقال
      zoom: it.focus ? { fx: it.focus.x * SC, fy: it.focus.y * SC, s: it.focus.s, at: it.tap ? Math.max(0.7, d - 0.9 - 2.3) : 0.9 } : null, chapter: it.chapter, chapterTitle: ch.title, step, steps,
      firstInChapter: step === 1, lastInChapter: !next || next.type !== "shot", nextSameChapter: !!(next && next.type === "shot"),
      prevIdx }, d);
    prevIdx = idx++;
  });
  add({ type: "outro" }, 6.5);
  return { total: +t.toFixed(3), chapters: chapters.length, segments: segs };
}

async function openStage(browser, tl) {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  page.on("pageerror", (e) => console.log("pageerror:", e.message));
  await page.goto("file://" + path.join(__dirname, "player.html"));
  await page.evaluate((x) => window.setup(x), tl);
  return page;
}

async function renderRange(browser, tl, from, to, file) {
  const page = await openStage(browser, tl);
  const ff = spawn("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", String(FPS),
    "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
    "-r", String(FPS), "-g", String(FPS * 2), file], { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((res, rej) => ff.on("close", (c) => (c === 0 ? res() : rej(new Error("ffmpeg " + c)))));
  for (let f = from; f < to; f++) {
    await page.evaluate((x) => window.renderAt(x), f / FPS);
    const buf = await page.screenshot({ type: "jpeg", quality: 94 });
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
    if ((f - from) % 300 === 0) console.log(`  ${path.basename(file)}: ${f - from}/${to - from}`);
  }
  ff.stdin.end();
  await done;
  await page.close();
}

(async () => {
  const m = JSON.parse(fs.readFileSync(path.join(SHOTS, "manifest.json"), "utf8"));
  const tl = timeline(m);
  fs.writeFileSync(path.join(path.dirname(OUT), "timeline.json"), JSON.stringify(tl, null, 1));
  console.log(`المدة ${tl.total.toFixed(1)} ث · ${tl.segments.length} مقطعاً`);
  const browser = await chromium.launch();
  if (PREVIEW) {
    const page = await openStage(browser, tl);
    for (const s of PREVIEW.split(",").map(Number)) {
      await page.evaluate((x) => window.renderAt(x), s);
      const f = path.join(path.dirname(OUT), `preview_${String(s).replace(".", "_")}.png`);
      await page.screenshot({ path: f });
      console.log("  ✔", f);
    }
    await browser.close();
    return;
  }
  const N = Math.ceil(tl.total * FPS);
  const per = Math.ceil(N / JOBS);
  const parts = [];
  const t0 = Date.now();
  await Promise.all(Array.from({ length: JOBS }, (_, j) => {
    const f = path.join(path.dirname(OUT), `part${j}.mp4`);
    parts.push(f);
    return renderRange(browser, tl, j * per, Math.min(N, (j + 1) * per), f);
  }));
  await browser.close();
  const list = path.join(path.dirname(OUT), "parts.txt");
  fs.writeFileSync(list, parts.map((p) => `file '${p}'`).join("\n"));
  await new Promise((res, rej) => spawn("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
    "-i", list, "-c", "copy", "-movflags", "+faststart", OUT], { stdio: "inherit" }).on("close", (c) => (c ? rej(new Error("concat")) : res())));
  console.log(`✔ ${OUT} — ${N} إطاراً في ${((Date.now() - t0) / 1000).toFixed(0)} ث`);
})().catch((e) => { console.error(e); process.exit(1); });
