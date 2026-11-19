/* البحث بالصورة في دليل الموديلات (5.10) — يعمل كله في متصفّح الجوال.
 *
 * 1) حزمة الأدوات على جهاز المصنع (محرّك ONNX ونموذج الرؤية) — تُنزَّل مرةً
 *    وتُحفظ في الجوال.
 * 2) فهرس الدليل: لكل موديلٍ بصماتُ صورته (الطقم كاملاً · كل قطعة · نوافذ).
 *    يُحسب هنا لما لم يُحسب بعد ويُحفظ على جهاز المصنع، فلا يُعاد.
 * 3) صورة المدير: يحدّد القطعة بإطار، فتُحسب بصماتها بقصّاتٍ متعددة،
 *    وتُقارن ببصمات كل موديل — فيظهر الأقرب أولاً مع ما بالخزنة وعند المناديب.
 */
(function () {
  'use strict';
  var D = JSON.parse(document.getElementById('vis-data').textContent);
  var BASE = D.base;
  var $ = function (id) { return document.getElementById(id); };
  var CAT = D.catalog || [];
  var byKey = {};
  CAT.forEach(function (c) { byKey[c.k] = c; });

  var M = null;          // manifest الحزمة
  var sess = null;       // جلسة النموذج
  var IDX = {};          // مفتاح الصورة ← {v, e:[Float32Array], k:[]}
  var ready = false, readyWaiters = [];
  var shots = [];        // بصمات لقطات المدير (لقطة ثانية تُدمج)
  var photo = null;      // الصورة الحالية (ImageBitmap/Canvas) وإطارها
  var busy = false;

  // ═════════ أدوات صغيرة ═════════
  function show(id, on) { $(id).hidden = !on; }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }
  function fail(msg) {
    var e = $('err'); e.textContent = msg; e.hidden = false;
  }
  function prep(title, done, total, sub) {
    show('prep', true);
    $('prepT').textContent = title;
    $('prepB').style.width = total ? Math.min(100, Math.round(100 * done / total)) + '%' : '0';
    $('prepS').textContent = sub || '';
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function mb(n) { return (n / 1048576).toFixed(n > 10485760 ? 0 : 1) + ' م.ب'; }

  // ═════════ 1) الحزمة ═════════
  // طلبٌ بمهلة: لا ينتظر الجوال جهازاً لا يردّ إلى الأبد
  function getJSON(url, ms) {
    var ac = self.AbortController ? new AbortController() : null;
    var tm = setTimeout(function () { if (ac) ac.abort(); }, ms || 20000);
    return fetch(url, {cache: 'no-store', credentials: 'same-origin', signal: ac ? ac.signal : undefined})
      .then(function (r) { clearTimeout(tm); return r.json(); },
            function (e) { clearTimeout(tm); throw e; });
  }
  function waitPack() {
    return getJSON(BASE + '/vis/status', 20000)
      .catch(function () {
        prep('جهاز المصنع لا يردّ الآن — تُعاد المحاولة…', 0, 0, 'تأكّد أن البرنامج مفتوحٌ على جهاز المصنع.');
        return sleep(5000).then(function () { return {state: 'retry'}; });
      })
      .then(function (st) {
        if (st.state === 'retry') return waitPack();
        if (st.state === 'ready') return st.manifest;
        if (st.state === 'error') {
          prep('تعذّر تنزيل أداة البحث على جهاز المصنع', 0, 0,
               (st.error || '') + ' — تُعاد المحاولة تلقائياً…');
          return sleep(8000).then(waitPack);
        }
        prep('جهاز المصنع ينزّل أداة البحث بالصورة (مرةً واحدة)…',
             st.done || 0, st.total || 0,
             st.total ? mb(st.done || 0) + ' من ' + mb(st.total) : '');
        return sleep(1500).then(waitPack);
      });
  }

  function loadScript(src) {
    return new Promise(function (ok, no) {
      var s = document.createElement('script');
      s.src = src; s.onload = ok;
      s.onerror = function () { no(new Error('تعذّر تحميل المحرّك')); };
      document.head.appendChild(s);
    });
  }

  // النموذج: من ذاكرة الجوال إن حُفظ، وإلا يُنزَّل بشريط تقدّم ثم يُحفظ
  function loadModel(url, size) {
    var CK = 'aur-vis-' + D.pack;
    var useCache = !!(self.caches && self.isSecureContext);
    var fromNet = function () {
      return fetch(url, {credentials: 'same-origin'}).then(function (r) {
        if (!r.ok) throw new Error('تعذّر تنزيل النموذج (' + r.status + ')');
        var total = +r.headers.get('Content-Length') || size || 0;
        if (!r.body || !r.body.getReader) return r.arrayBuffer();
        var rd = r.body.getReader(), parts = [], got = 0;
        var pump = function () {
          return rd.read().then(function (x) {
            if (x.done) return;
            parts.push(x.value); got += x.value.length;
            prep('تنزيل نموذج الرؤية إلى الجوال (مرةً واحدة)…', got, total,
                 mb(got) + (total ? ' من ' + mb(total) : ''));
            return pump();
          });
        };
        return pump().then(function () {
          var buf = new Uint8Array(got), o = 0;
          parts.forEach(function (p) { buf.set(p, o); o += p.length; });
          return buf.buffer;
        });
      });
    };
    if (!useCache) return fromNet();
    return caches.keys().then(function (ks) {
      // حزمةٌ أقدم: تُحذف ذاكرتها
      return Promise.all(ks.filter(function (k) {
        return k.indexOf('aur-vis-') === 0 && k !== CK;
      }).map(function (k) { return caches.delete(k); }));
    }).then(function () { return caches.open(CK); }).then(function (c) {
      return c.match(url).then(function (hit) {
        if (hit) return hit.arrayBuffer();
        return fromNet().then(function (buf) {
          return c.put(url, new Response(buf.slice(0), {headers: {'Content-Type': 'application/octet-stream'}}))
            .catch(function () { /* المساحة ممتلئة: يكفي هذه المرة */ })
            .then(function () { return buf; });
        });
      });
    }).catch(function () { return fromNet(); });
  }

  function startEngine(man) {
    M = man;
    return loadScript(BASE + '/vis/pack/ort.wasm.min.js').then(function () {
      var ort = self.ort;
      ort.env.wasm.wasmPaths = BASE + '/vis/pack/';
      var hc = navigator.hardwareConcurrency || 2;
      ort.env.wasm.numThreads = self.crossOriginIsolated ? Math.max(1, Math.min(4, hc - 1)) : 1;
      ort.env.wasm.proxy = true;
      return loadModel(BASE + '/vis/pack/model.onnx', M.size_bytes);
    }).then(function (buf) {
      prep('تشغيل نموذج الرؤية…', 1, 1, '');
      return self.ort.InferenceSession.create(buf, {
        executionProviders: ['wasm'], graphOptimizationLevel: 'all'});
    }).then(function (s) { sess = s; });
  }

  // ═════════ الصور والمساقط ═════════
  function canvasOf(w, h) {
    var c = document.createElement('canvas'); c.width = w; c.height = h; return c;
  }
  function loadImage(url) {
    return fetch(url, {credentials: 'same-origin'}).then(function (r) {
      if (!r.ok) throw new Error('img ' + r.status);
      return r.blob();
    }).then(function (b) { return createImageBitmap(b); });
  }
  function toCanvas(img, maxSide) {
    var w = img.width, h = img.height, s = Math.min(1, maxSide / Math.max(w, h));
    var c = canvasOf(Math.max(1, Math.round(w * s)), Math.max(1, Math.round(h * s)));
    var g = c.getContext('2d');
    g.imageSmoothingQuality = 'high';
    g.drawImage(img, 0, 0, c.width, c.height);
    return c;
  }
  // لون الخلفية: الوسيط في حوافّ الصورة
  function edgeColor(px, w, h) {
    var rs = [], gs = [], bs = [];
    var add = function (x, y) { var i = (y * w + x) * 4; rs.push(px[i]); gs.push(px[i + 1]); bs.push(px[i + 2]); };
    for (var x = 0; x < w; x++) { add(x, 0); add(x, h - 1); }
    for (var y = 0; y < h; y++) { add(0, y); add(w - 1, y); }
    var med = function (a) { a.sort(function (p, q) { return p - q; }); return a[a.length >> 1]; };
    return [med(rs), med(gs), med(bs)];
  }
  function fgMask(c) {
    var w = c.width, h = c.height, px = c.getContext('2d').getImageData(0, 0, w, h).data;
    var bg = edgeColor(px, w, h), m = new Uint8Array(w * h), n = 0;
    for (var i = 0, j = 0; j < m.length; i += 4, j++) {
      var d = Math.max(Math.abs(px[i] - bg[0]), Math.abs(px[i + 1] - bg[1]), Math.abs(px[i + 2] - bg[2]));
      if (d > 28) { m[j] = 1; n++; }
    }
    return {m: m, w: w, h: h, n: n, bg: bg};
  }
  function bboxOf(mk, x0, y0, x1, y1) {
    x0 = x0 || 0; y0 = y0 || 0; x1 = x1 == null ? mk.w : x1; y1 = y1 == null ? mk.h : y1;
    var a = 1e9, b = 1e9, c = -1, d = -1, cnt = 0;
    for (var y = y0; y < y1; y++) for (var x = x0; x < x1; x++) if (mk.m[y * mk.w + x]) {
      cnt++; if (x < a) a = x; if (y < b) b = y; if (x > c) c = x; if (y > d) d = y;
    }
    return c < 0 ? null : {x: a, y: b, w: c - a + 1, h: d - b + 1, n: cnt};
  }
  // مكوّناتٌ متصلة (بعد تمديدٍ بسيط) — كل قطعةٍ في الطقم وحدها
  function components(mk) {
    var w = mk.w, h = mk.h, r = 3, dil = new Uint8Array(w * h);
    var rowMax = new Uint8Array(w * h);
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var v = 0;
      for (var dx = -r; dx <= r && !v; dx++) { var xx = x + dx; if (xx >= 0 && xx < w && mk.m[y * w + xx]) v = 1; }
      rowMax[y * w + x] = v;
    }
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
      v = 0;
      for (var dy = -r; dy <= r && !v; dy++) { var yy = y + dy; if (yy >= 0 && yy < h && rowMax[yy * w + x]) v = 1; }
      dil[y * w + x] = v;
    }
    var lab = new Int32Array(w * h), comps = [], q = new Int32Array(w * h);
    for (var s = 0; s < w * h; s++) {
      if (!dil[s] || lab[s]) continue;
      var id = comps.length + 1, qh = 0, qt = 0, area = 0, fg = 0;
      var a = 1e9, b = 1e9, c2 = -1, d2 = -1;
      lab[s] = id; q[qt++] = s;
      while (qh < qt) {
        var p = q[qh++], px = p % w, py = (p - px) / w;
        area++; if (mk.m[p]) fg++;
        if (px < a) a = px; if (py < b) b = py; if (px > c2) c2 = px; if (py > d2) d2 = py;
        for (var oy = -1; oy <= 1; oy++) for (var ox = -1; ox <= 1; ox++) {
          var nx = px + ox, ny = py + oy;
          if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
          var t = ny * w + nx;
          if (dil[t] && !lab[t]) { lab[t] = id; q[qt++] = t; }
        }
      }
      comps.push({x: a, y: b, w: c2 - a + 1, h: d2 - b + 1, area: area, fg: fg});
    }
    return comps;
  }
  // مربّعٌ محشوّ حول منطقة (بلون الخلفية) — كما يُجهَّز للنموذج
  function padSquare(src, box, fill, margin) {
    var s = Math.round(Math.max(box.w, box.h) * (1 + margin));
    var c = canvasOf(s, s), g = c.getContext('2d');
    g.fillStyle = 'rgb(' + fill.join(',') + ')';
    g.fillRect(0, 0, s, s);
    g.imageSmoothingQuality = 'high';
    g.drawImage(src, box.x, box.y, box.w, box.h,
                Math.round((s - box.w) / 2), Math.round((s - box.h) / 2), box.w, box.h);
    return c;
  }
  function centerSquare(src, frac) {
    var s = Math.round(Math.min(src.width, src.height) * frac);
    var c = canvasOf(s, s);
    c.getContext('2d').drawImage(src, Math.round((src.width - s) / 2), Math.round((src.height - s) / 2), s, s, 0, 0, s, s);
    return c;
  }
  function flipped(src) {
    var c = canvasOf(src.width, src.height), g = c.getContext('2d');
    g.translate(src.width, 0); g.scale(-1, 1); g.drawImage(src, 0, 0);
    return c;
  }

  // زوايا صورة الكتالوج: الطقم كاملاً · كل قطعة · نوافذ (حسب الحزمة)
  function catalogViews(img) {
    var V = M.views || {};
    var c = toCanvas(img, V.work || 384);
    var mk = fgMask(c), box = bboxOf(mk), out = [], kinds = [];
    var white = [255, 255, 255];
    if (!box) { out.push(padSquare(c, {x: 0, y: 0, w: c.width, h: c.height}, white, 0)); return {v: out, k: ['f']}; }
    out.push(padSquare(c, box, white, 0.06)); kinds.push('f');
    if (V.pieces) {
      var comps = components(mk).filter(function (p) { return p.fg > 0.025 * mk.n; });
      if (comps.length > 1) {
        comps.sort(function (p, q) { return q.area - p.area; });
        comps.slice(0, V.pieces).forEach(function (p) {
          out.push(padSquare(c, p, white, 0.15)); kinds.push('p');
        });
      }
    }
    if (V.windows) {
      var W = box.w, H = box.h, cw = W * 0.55, ch = H * 0.55;
      [[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0.5]].forEach(function (f) {
        var x = Math.round(box.x + f[0] * (W - cw)), y = Math.round(box.y + f[1] * (H - ch));
        var sub = {x: x, y: y, w: Math.round(cw), h: Math.round(ch)};
        var bb = bboxOf(mk, sub.x, sub.y, sub.x + sub.w, sub.y + sub.h);
        if (bb && bb.n > 0.01 * sub.w * sub.h) { out.push(padSquare(c, sub, white, 0.05)); kinds.push('w'); }
      });
    }
    // الطقم على خلفيةٍ داكنة (كالمخمل الأسود في المحلّات)
    if (V.dark) {
      var dk = [24, 22, 26], g = c.getContext('2d'), id = g.getImageData(0, 0, c.width, c.height);
      var dc = canvasOf(c.width, c.height), dg = dc.getContext('2d'), od = dg.createImageData(c.width, c.height);
      for (var i = 0, j = 0; j < mk.m.length; i += 4, j++) {
        var on = mk.m[j];
        od.data[i] = on ? id.data[i] : dk[0]; od.data[i + 1] = on ? id.data[i + 1] : dk[1];
        od.data[i + 2] = on ? id.data[i + 2] : dk[2]; od.data[i + 3] = 255;
      }
      dg.putImageData(od, 0, 0);
      out.push(padSquare(dc, box, dk, 0.06)); kinds.push('d');
    }
    // الطقم مائلاً (الجوال يصوّره بزاوية): انضغاطٌ رأسي ودورانٌ خفيف
    (V.tilts || []).forEach(function (t) {
      var f = out[0], s = f.width, tc = canvasOf(s, s), tg = tc.getContext('2d');
      tg.fillStyle = '#fff'; tg.fillRect(0, 0, s, s);
      tg.translate(s / 2, s / 2); tg.scale(1, t[0]); tg.rotate(-t[1] * Math.PI / 180);
      tg.imageSmoothingQuality = 'high';
      tg.drawImage(f, -s / 2, -s / 2);
      out.push(tc); kinds.push('s');
    });
    return {v: out.slice(0, 16), k: kinds.slice(0, 16)};
  }

  // قصّات صورة المدير داخل الإطار الذي حدّده
  function queryViews(src, box) {
    var Q = M.query || {};
    var reg = canvasOf(Math.round(box.w), Math.round(box.h));
    reg.getContext('2d').drawImage(src, box.x, box.y, box.w, box.h, 0, 0, reg.width, reg.height);
    var lim = toCanvas(reg, 768);
    var px = lim.getContext('2d').getImageData(0, 0, lim.width, lim.height).data;
    var fill = edgeColor(px, lim.width, lim.height);
    var sq = (Math.abs(lim.width - lim.height) < 0.04 * Math.max(lim.width, lim.height))
      ? lim : padSquare(lim, {x: 0, y: 0, w: lim.width, h: lim.height}, fill, 0);
    var out = [sq];
    (Q.crops || []).forEach(function (f) { out.push(centerSquare(sq, f)); });
    if (Q.flip) out.push(flipped(sq));
    return out;
  }

  // ═════════ النموذج: صورٌ ← بصمات ═════════
  function tensorOf(cs) {
    var S = M.input || 224, n = cs.length, mean = M.mean, std = M.std;
    var data = new Float32Array(n * 3 * S * S), plane = S * S;
    var t = canvasOf(S, S), g = t.getContext('2d', {willReadFrequently: true});
    g.imageSmoothingQuality = 'high';
    for (var b = 0; b < n; b++) {
      g.clearRect(0, 0, S, S);
      g.drawImage(cs[b], 0, 0, S, S);
      var px = g.getImageData(0, 0, S, S).data, o = b * 3 * plane;
      for (var i = 0, j = 0; j < plane; i += 4, j++) {
        data[o + j] = (px[i] / 255 - mean[0]) / std[0];
        data[o + plane + j] = (px[i + 1] / 255 - mean[1]) / std[1];
        data[o + 2 * plane + j] = (px[i + 2] / 255 - mean[2]) / std[2];
      }
    }
    return new self.ort.Tensor('float32', data, [n, 3, S, S]);
  }
  function l2(v) {
    var s = 0; for (var i = 0; i < v.length; i++) s += v[i] * v[i];
    s = Math.sqrt(s) || 1;
    for (i = 0; i < v.length; i++) v[i] /= s;
    return v;
  }
  function pool(out, n) {
    var P = M.pool || 'cls', key = M.output || Object.keys(out)[0], t = out[key];
    if (P === 'embeds') {
      var dd = t.dims[t.dims.length - 1], res = [];
      for (var b = 0; b < n; b++) res.push(l2(Float32Array.from(t.data.subarray(b * dd, (b + 1) * dd))));
      return res;
    }
    var T = t.dims[1], Dm = t.dims[2], skip = M.skip || 1, outv = [];
    for (b = 0; b < n; b++) {
      var base = b * T * Dm;
      var cls = Float32Array.from(t.data.subarray(base, base + Dm));
      var mean = new Float32Array(Dm), gem = new Float32Array(Dm), np = T - skip;
      for (var k = skip; k < T; k++) {
        var o = base + k * Dm;
        for (var d = 0; d < Dm; d++) {
          var x = t.data[o + d]; mean[d] += x;
          if (P === 'gem') { var y = x > 1e-6 ? x : 1e-6; gem[d] += y * y * y; }
        }
      }
      for (d = 0; d < Dm; d++) { mean[d] /= np; gem[d] = Math.cbrt(gem[d] / np); }
      if (P === 'cls') outv.push(l2(cls));
      else if (P === 'mean') outv.push(l2(mean));
      else if (P === 'gem') outv.push(l2(gem));
      else {                                  // cls+mean
        l2(cls); l2(mean);
        var v = new Float32Array(2 * Dm); v.set(cls); v.set(mean, Dm);
        outv.push(l2(v));
      }
    }
    return outv;
  }
  function embed(cs) {
    var bs = M.batch || 4, res = [], i = 0;
    var step = function () {
      if (i >= cs.length) return Promise.resolve(res);
      var part = cs.slice(i, i + bs); i += bs;
      var feeds = {}; feeds[M.input_name || 'pixel_values'] = tensorOf(part);
      // المخرج المطلوب وحده (لا تُنسخ رموز الصورة كلها من المحرّك)
      var run = M.output ? sess.run(feeds, [M.output]) : sess.run(feeds);
      return run.then(function (out) {
        res = res.concat(pool(out, part.length));
        return step();
      });
    };
    return step();
  }

  // بصمةٌ مضغوطة: مقياس float32 + int8 لكل بُعد (base64)
  function pack8(v) {
    var mx = 1e-9; for (var i = 0; i < v.length; i++) mx = Math.max(mx, Math.abs(v[i]));
    var sc = mx / 127, buf = new ArrayBuffer(4 + v.length), dv = new DataView(buf);
    dv.setFloat32(0, sc, true);
    var q = new Int8Array(buf, 4);
    for (i = 0; i < v.length; i++) q[i] = Math.max(-127, Math.min(127, Math.round(v[i] / sc)));
    var s = '', u = new Uint8Array(buf);
    for (i = 0; i < u.length; i++) s += String.fromCharCode(u[i]);
    return btoa(s);
  }
  function unpack8(b64) {
    var s = atob(b64), u = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
    var sc = new DataView(u.buffer).getFloat32(0, true), q = new Int8Array(u.buffer, 4);
    var v = new Float32Array(q.length);
    for (i = 0; i < q.length; i++) v[i] = q[i] * sc;
    return l2(v);
  }

  // ═════════ 2) فهرس الدليل ═════════
  function loadIndex() {
    return fetch(BASE + '/vis/index', {cache: 'no-store', credentials: 'same-origin'})
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d.model !== M.id) return;
        Object.keys(d.items || {}).forEach(function (k) {
          var it = d.items[k];
          if (byKey[k] && byKey[k].v === it.v) {
            IDX[k] = {v: it.v, e: it.e.map(unpack8), k: it.k || []};
          }
        });
      });
  }
  function postIndex(items, dim) {
    return fetch(BASE + '/vis/index', {
      method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-Csrf': D.csrf},
      body: JSON.stringify({model: M.id, dim: dim, items: items})
    }).then(function (r) { return r.ok; }).catch(function () { return false; });
  }
  function buildIndex() {
    var todo = CAT.filter(function (c) { return !IDX[c.k]; });
    if (!todo.length) return Promise.resolve();
    var total = todo.length, done = 0, pend = {}, pendBytes = 0, dim = 0;
    var t0 = Date.now();
    var flush = function () {
      if (!pendBytes) return Promise.resolve();
      var items = pend; pend = {}; pendBytes = 0;
      return postIndex(items, dim);
    };
    var one = function () {
      if (!todo.length) return flush();
      var c = todo.shift();
      return loadImage(c.img).then(function (img) {
        var cv = catalogViews(img);
        return embed(cv.v).then(function (vecs) {
          dim = vecs[0].length;
          IDX[c.k] = {v: c.v, e: vecs, k: cv.k};
          var enc = vecs.map(pack8);
          pend[c.k] = {v: c.v, e: enc, k: cv.k};
          pendBytes += enc.join('').length + 60;
        });
      }).catch(function () { /* صورةٌ تعذّرت: تُتخطّى هذه المرة */ })
        .then(function () {
          done++;
          var el = (Date.now() - t0) / done, left = Math.round(el * (total - done) / 1000);
          prep('تجهيز صور الدليل للبحث (مرةً واحدة)…', done, total,
               done + ' من ' + total + ' موديل' + (done > 3 && left > 5
                 ? ' · بقي نحو ' + (left > 90 ? Math.round(left / 60) + ' دقيقة' : left + ' ثانية') : ''));
          return (pendBytes > 80000 ? flush() : Promise.resolve()).then(one);
        });
    };
    return one();
  }

  // ═════════ 3) المطابقة ═════════
  function score(qs) {
    var agg = (M.agg || 'meanmax'), out = [];
    CAT.forEach(function (c) {
      var it = IDX[c.k]; if (!it) return;
      var tot = 0, best = -2;
      qs.forEach(function (q) {
        var b = -2;
        it.e.forEach(function (e) {
          var s = 0; for (var d = 0; d < q.length; d++) s += q[d] * e[d];
          if (s > b) b = s;
        });
        tot += b; if (b > best) best = b;
      });
      out.push({c: c, s: agg === 'max' ? best : tot / qs.length});
    });
    return out;
  }
  function rank() {
    // لقطاتٌ متعددة للطقم نفسه: متوسط درجاتها
    var sum = {};
    shots.forEach(function (qs) {
      score(qs).forEach(function (r) {
        (sum[r.c.k] = sum[r.c.k] || {c: r.c, s: 0}).s += r.s / shots.length;
      });
    });
    return Object.keys(sum).map(function (k) { return sum[k]; })
      .sort(function (a, b) { return b.s - a.s; });
  }
  function band(s, i, list) {
    var T = M.thr || {hi: 0.7, mid: 0.55};
    var gap = list.length > 1 ? s - list[1].s : 1;
    if (i === 0 && s >= T.hi && gap >= (T.gap || 0.02)) return ['s-hi', 'تطابقٌ قوي'];
    if (s >= T.mid) return ['s-mid', 'قريب'];
    return ['s-lo', 'تشابهٌ ضعيف'];
  }
  function card(r, i, list) {
    var c = r.c, b = band(r.s, i, list), unit = esc(D.unit);
    var pct = Math.max(0, Math.min(100, Math.round(100 * r.s)));
    var sold = c.sold.length ? '<h3 class="out">طرف المناديب</h3><table><tr><th>رقم التشغيل</th><th>الوزن</th><th>مع من</th><th>التاريخ</th></tr>' +
      c.sold.map(function (x) { return '<tr><td>' + esc(x[0]) + '</td><td class="n">' + esc(x[1]) + '</td><td>' + esc(x[2]) + '</td><td class="n">' + esc(x[3]) + '</td></tr>'; }).join('') + '</table>' : '';
    var stock = c.stock.length ? '<h3 class="in">بالخزنة (متاح للبيع)</h3><table><tr><th>رقم التشغيل</th><th>الوزن</th><th>أُدخل</th></tr>' +
      c.stock.map(function (x) { return '<tr><td>' + esc(x[0]) + '</td><td class="n">' + esc(x[1]) + '</td><td class="n">' + esc(x[2]) + '</td></tr>'; }).join('') + '</table>' : '';
    var n = c.sold.length + c.stock.length;
    return '<article class="hit' + (i === 0 ? ' top' : '') + '">' +
      '<a href="' + esc(c.full) + '" target="_blank" rel="noopener"><img loading="lazy" src="' + esc(c.img) + '" alt="' + esc(c.m) + '"></a>' +
      '<div><h2><span>الموديل ' + esc(c.m) + '</span><span class="sim ' + b[0] + '">' + b[1] + ' · ' + pct + '%</span></h2>' +
      '<div class="chips"><span class="chip in">بالخزنة ' + c.in + ' · ' + esc(c.inw) + ' ' + unit + '</span>' +
      '<span class="chip out">عند المناديب ' + c.out + ' · ' + esc(c.outw) + ' ' + unit + '</span></div></div>' +
      (n ? '<details' + (i === 0 ? ' open' : '') + '><summary>التفاصيل — ' + n + ' قطعة</summary>' + stock + sold + '</details>' : '') +
      '</article>';
  }
  function render() {
    var list = rank(), top = list.slice(0, 12);
    $('rT').textContent = list.length ? 'أقرب الموديلات لصورتك' : 'لا موديلات بصورٍ في الدليل';
    $('rS').textContent = (shots.length > 1 ? 'من ' + shots.length + ' لقطات · ' : '') +
      'مقارنةً بـ' + list.length + ' موديل — الأقرب أولاً';
    $('list').innerHTML = top.map(function (r, i) { return card(r, i, list); }).join('') +
      (list.length > 12 ? '<button class="alt more" type="button" id="more">عرض المزيد</button>' : '');
    var more = $('more');
    if (more) more.onclick = function () {
      $('list').innerHTML = list.slice(0, 40).map(function (r, i) { return card(r, i, list); }).join('');
    };
    show('res', true);
  }

  // ═════════ 4) الكاميرا والإطار ═════════
  var box = null, stageScale = 1;
  function openPhoto(file, add) {
    if (!file) return;
    show('err', false);
    createImageBitmap(file).then(function (bm) {
      var c = toCanvas(bm, 1600);
      photo = {c: c, add: !!add};
      var cv = $('cv');
      cv.width = c.width; cv.height = c.height;
      cv.getContext('2d').drawImage(c, 0, 0);
      show('intro', false); show('crop', true);
      if (!add) { show('res', false); }
      requestAnimationFrame(function () {
        stageScale = cv.getBoundingClientRect().width / c.width;
        var m = 0.05;
        box = {x: c.width * m, y: c.height * m, w: c.width * (1 - 2 * m), h: c.height * (1 - 2 * m)};
        drawBox();
        $('crop').scrollIntoView({behavior: 'smooth', block: 'start'});
      });
    }).catch(function () { fail('تعذّر فتح الصورة — جرّب صورةً أخرى'); });
  }
  function drawBox() {
    var b = $('box');
    b.style.left = (box.x * stageScale) + 'px';
    b.style.top = (box.y * stageScale) + 'px';
    b.style.width = (box.w * stageScale) + 'px';
    b.style.height = (box.h * stageScale) + 'px';
  }
  (function dragging() {
    var mode = null, sx = 0, sy = 0, sb = null;
    var down = function (e) {
      if (!photo) return;
      var t = e.target;
      mode = t.classList.contains('h') ? t.classList[1] : (t.id === 'box' ? 'move' : null);
      if (!mode) return;
      e.preventDefault();
      sx = e.clientX; sy = e.clientY; sb = {x: box.x, y: box.y, w: box.w, h: box.h};
      t.setPointerCapture && t.setPointerCapture(e.pointerId);
    };
    var move = function (e) {
      if (!mode) return;
      var dx = (e.clientX - sx) / stageScale, dy = (e.clientY - sy) / stageScale;
      var W = photo.c.width, H = photo.c.height, min = Math.min(W, H) * 0.08;
      var b = {x: sb.x, y: sb.y, w: sb.w, h: sb.h};
      if (mode === 'move') { b.x = Math.max(0, Math.min(W - b.w, sb.x + dx)); b.y = Math.max(0, Math.min(H - b.h, sb.y + dy)); }
      else {
        if (mode.indexOf('l') >= 0) { var nx = Math.max(0, Math.min(sb.x + sb.w - min, sb.x + dx)); b.w = sb.w + (sb.x - nx); b.x = nx; }
        if (mode.indexOf('r') >= 0) b.w = Math.max(min, Math.min(W - sb.x, sb.w + dx));
        if (mode.indexOf('t') >= 0) { var ny = Math.max(0, Math.min(sb.y + sb.h - min, sb.y + dy)); b.h = sb.h + (sb.y - ny); b.y = ny; }
        if (mode.indexOf('b') >= 0) b.h = Math.max(min, Math.min(H - sb.y, sb.h + dy));
      }
      box = b; drawBox();
    };
    var up = function () { mode = null; };
    var st = $('stage');
    st.addEventListener('pointerdown', down);
    st.addEventListener('pointermove', move);
    st.addEventListener('pointerup', up);
    st.addEventListener('pointercancel', up);
    window.addEventListener('resize', function () {
      if (photo && !$('crop').hidden) { stageScale = $('cv').getBoundingClientRect().width / photo.c.width; drawBox(); }
    });
  })();

  function whenReady() {
    if (ready) return Promise.resolve();
    return new Promise(function (r) { readyWaiters.push(r); });
  }
  function search(full) {
    if (!photo || busy) return;
    busy = true;
    var b = full ? {x: 0, y: 0, w: photo.c.width, h: photo.c.height} : box;
    var thumb = canvasOf(128, 128);
    thumb.getContext('2d').drawImage(photo.c, b.x, b.y, b.w, b.h, 0, 0, 128, 128);
    $('qimg').src = thumb.toDataURL('image/jpeg', 0.8);
    $('go').disabled = true; $('go').textContent = ready ? '… جارٍ البحث' : '… بانتظار تجهيز الأداة';
    whenReady().then(function () {
      return embed(queryViews(photo.c, b));
    }).then(function (qs) {
      if (!photo.add) shots.length = 0;
      shots.push(qs);
      show('crop', false);
      render();
      $('res').scrollIntoView({behavior: 'smooth', block: 'start'});
    }).catch(function (e) { fail('تعذّر البحث: ' + (e && e.message || e)); })
      .then(function () { busy = false; $('go').disabled = false; $('go').textContent = '🔍 ابحث'; });
  }

  $('cam').onchange = function () { openPhoto(this.files[0], false); this.value = ''; };
  $('gal').onchange = function () { openPhoto(this.files[0], false); this.value = ''; };
  $('cam2').onchange = function () { openPhoto(this.files[0], false); this.value = ''; };
  $('add').onchange = function () { openPhoto(this.files[0], true); this.value = ''; };
  $('go').onclick = function () { search(false); };
  $('full').onclick = function () { search(true); };

  // ═════════ التشغيل ═════════
  if (!self.WebAssembly || !self.createImageBitmap || !self.fetch) {
    fail('متصفّح هذا الجوال قديمٌ لا يدعم البحث بالصورة — حدّثه أو افتح الرابط في Chrome أو Safari حديث.');
    return;
  }
  if (!CAT.length) {
    prep('لا توجد صورٌ في الدليل بعد', 0, 0, 'أضف صور الموديلات من شاشة «دليل الموديلات» في البرنامج.');
    return;
  }
  prep('جارٍ الاتصال بجهاز المصنع…', 0, 0, 'يمكنك التصوير الآن — يبدأ البحث متى جهزت الأداة.');
  waitPack().then(startEngine).then(loadIndex).then(buildIndex).then(function () {
    ready = true;
    show('prep', false);
    readyWaiters.splice(0).forEach(function (r) { r(); });
    window.__visReady = true;
  }).catch(function (e) {
    fail('تعذّر تجهيز البحث بالصورة: ' + (e && e.message || e));
  });
  // للاختبار الآلي
  window.__vis = {embed: function (cs) { return embed(cs); }, idx: IDX, rank: rank,
                  shots: shots, manifest: function () { return M; }};
})();
