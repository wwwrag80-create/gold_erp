/* أدوات الواجهة: بناء العناصر، الرسائل، التأكيد، الاختيار، خانات الأرقام. */
(function (root) {
  "use strict";
  const { f2, parseNum } = root.Num;

  function h(tag, props, ...kids) {
    const el = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v === undefined || v === null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "html") el.innerHTML = v;
        else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
        else if (k === "value") el.value = v;
        else if (k === "checked") el.checked = !!v;
        else el.setAttribute(k, v === true ? "" : v);
      }
    }
    for (const c of kids.flat(Infinity)) {
      if (c === null || c === undefined || c === false) continue;
      el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  let toastTimer = null;
  function toast(msg, kind) {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.className = kind === "err" ? "err" : "";
    t.style.display = "block";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.style.display = "none"; }, kind === "err" ? 5200 : 2600);
  }
  function err(e) { toast((e && e.message) || String(e), "err"); }

  // إغلاق نافذةٍ يرجع خطوةً في السجل (history.back) — وحدث الرجوع يصل بعد
  // لحظة؛ فالنافذة التالية تنتظره، وإلا التقطته فأُغلقت فور فتحها
  let backPending = null;
  function sheet(build) {
    return (backPending || Promise.resolve()).then(() => openSheet(build));
  }
  function openSheet(build) {
    return new Promise((resolve) => {
      const wrap = h("div", { class: "sheet-wrap" });
      const box = h("div", { class: "sheet" });
      wrap.appendChild(box);
      let done = false;
      const close = (v) => {
        if (done) return;
        done = true;
        wrap.remove();
        window.removeEventListener("popstate", onPop);
        resolve(v);
      };
      // زرّ الرجوع في الجوال يُغلق النافذة لا الشاشة
      const onPop = () => close(undefined);
      history.pushState({ sheet: 1 }, "");
      window.addEventListener("popstate", onPop);
      const closeBack = (v) => {
        if (done) return;
        window.removeEventListener("popstate", onPop);
        if (history.state && history.state.sheet) {
          backPending = new Promise((res) => {
            const fin = () => { window.removeEventListener("popstate", fin); clearTimeout(t); backPending = null; res(); };
            const t = setTimeout(fin, 400);
            window.addEventListener("popstate", fin);
          });
          history.back();
        }
        close(v);
      };
      wrap.addEventListener("click", (e) => { if (e.target === wrap) closeBack(undefined); });
      build(box, closeBack);
      document.getElementById("sheet-root").appendChild(wrap);
      const first = box.querySelector("input,select,textarea");
      if (first && first.dataset.autofocus !== "no") setTimeout(() => first.focus(), 60);
    });
  }

  function confirmSheet(msg, ok, danger) {
    return sheet((box, close) => {
      box.append(
        h("h3", { text: "تأكيد" }),
        h("div", { style: { whiteSpace: "pre-line", lineHeight: "1.7" }, text: msg }),
        h("div", { class: "actions" },
          h("button", { class: "btn" + (danger ? " danger" : ""), onclick: () => close(true) }, ok || "موافق"),
          h("button", { class: "btn ghost", onclick: () => close(false) }, "إلغاء")));
    }).then((v) => !!v);
  }

  // قائمة اختيارٍ ببحث — `items`: [{id, title, sub}]
  function pickSheet(title, items, opts) {
    const o = opts || {};
    return sheet((box, close) => {
      const list = h("div");
      const q = h("input", { class: "in", placeholder: o.placeholder || "ابحث…", type: "search" });
      const render = () => {
        const t = q.value.trim();
        list.innerHTML = "";
        const hits = items.filter((it) => !t || (it.title + " " + (it.sub || "")).includes(t));
        for (const it of hits.slice(0, 200)) {
          list.appendChild(h("div", { class: "list-item", onclick: () => close(it) },
            h("div", { class: "grow" }, h("div", { class: "t", text: it.title }),
              it.sub ? h("div", { class: "muted small", text: it.sub }) : null),
            it.badge || null));
        }
        if (!hits.length) list.appendChild(h("div", { class: "empty", text: o.empty || "لا نتائج" }));
      };
      q.addEventListener("input", render);
      box.append(h("h3", { text: title }), q, h("div", { style: { height: "10px" } }));
      if (o.addLabel) {
        box.append(h("button", { class: "btn ghost block", style: { marginBottom: "10px" },
          onclick: () => close({ add: true }) }, o.addLabel));
      }
      box.append(list);
      render();
    });
  }

  // خانة رقم: أرقام عربية أو لاتينية، و«12+3» تُحسب عند المغادرة
  function numInput(opts) {
    const o = opts || {};
    const el = h("input", {
      class: "in n" + (o.hl ? " hl" : ""), inputmode: "decimal", autocomplete: "off",
      enterkeyhint: o.enter || "next", placeholder: o.placeholder || "",
    });
    el._val = o.value || 0;
    el.value = o.value ? (o.raw ? String(o.value) : f2(o.value, { sep: false })) : (o.blankZero === false ? "0.00" : "");
    el.getVal = () => {
      const t = el.value.trim();
      if (!t) return 0;
      const v = parseNum(t);
      return isFinite(v) ? v : NaN;
    };
    el.setVal = (v, raw) => {
      el.value = v ? (raw ? String(v) : f2(v, { sep: false })) : "";
    };
    el.isBlank = () => !el.value.trim();
    el.addEventListener("focus", () => setTimeout(() => el.select(), 0));
    el.addEventListener("blur", () => {
      const t = el.value.trim();
      if (!t) return;
      const v = parseNum(t);
      if (isFinite(v) && /[+\-]/.test(t.slice(1))) el.value = f2(v, { sep: false });
    });
    if (o.oninput) el.addEventListener("input", o.oninput);
    return el;
  }

  function field(label, input, cls) {
    return h("label", { class: "f" + (cls ? " " + cls : "") }, h("span", { text: label }), input);
  }

  // Enter ينقل للخانة التالية — والأخيرة تنفّذ `onLast`
  function enterChain(inputs, onLast) {
    inputs.forEach((el, i) => {
      el.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        const next = inputs.slice(i + 1).find((x) => !x.disabled && x.offsetParent !== null);
        if (next) next.focus(); else if (onLast) onLast();
      });
    });
  }

  // ينتظر رجوع السجل الذي يتبع إغلاق نافذة — قبل أي انتقالٍ بعدها
  function idle() { return backPending || Promise.resolve(); }

  root.UI = { h, toast, err, sheet, confirmSheet, pickSheet, numInput, field, enterChain, idle };
})(window);
