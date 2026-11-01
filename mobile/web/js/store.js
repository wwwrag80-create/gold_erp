/* حفظ البيانات في الجوال (IndexedDB) — كل سجلٍّ يُكتب وحده عند تغيّره،
 * والحالة كلها في الذاكرة أثناء العمل. فإن لم يتوفّر IndexedDB يُستعمل
 * localStorage بديلاً.
 */
(function (root) {
  "use strict";
  const DB_NAME = "jadeite_mobile", VER = 1;
  const STORES = ["shops", "invoices", "vouchers", "held", "meta"];
  let db = null, fallback = false;

  function open() {
    return new Promise((resolve) => {
      let req;
      try { req = indexedDB.open(DB_NAME, VER); } catch (e) { fallback = true; resolve(null); return; }
      req.onupgradeneeded = () => {
        const d = req.result;
        for (const s of STORES) {
          if (!d.objectStoreNames.contains(s)) {
            d.createObjectStore(s, { keyPath: s === "meta" ? "key" : "id" });
          }
        }
      };
      req.onsuccess = () => { db = req.result; resolve(db); };
      req.onerror = () => { fallback = true; resolve(null); };
    });
  }

  function all(store) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, "readonly");
      const r = tx.objectStore(store).getAll();
      r.onsuccess = () => resolve(r.result || []);
      r.onerror = () => reject(r.error);
    });
  }

  async function load() {
    const st = root.Domain.newState();
    await open();
    if (fallback || !db) {
      try {
        const raw = localStorage.getItem(DB_NAME);
        if (raw) return root.Domain.fromBackup(JSON.parse(raw));
      } catch (e) { /* يبدأ فارغاً */ }
      return st;
    }
    for (const s of ["shops", "invoices", "vouchers", "held"]) st[s] = await all(s);
    for (const m of await all("meta")) {
      if (m.key === "settings") Object.assign(st.settings, m.value || {});
      if (m.key === "seq") Object.assign(st.seq, m.value || {});
    }
    return st;
  }

  function write(ops) {
    // ops: [[store, "put"|"del", value]]
    if (fallback || !db) {
      try { localStorage.setItem(DB_NAME, JSON.stringify(root.Domain.toBackup(root.App.state))); }
      catch (e) { return Promise.reject(e); }
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const names = [...new Set(ops.map((o) => o[0]))];
      const tx = db.transaction(names, "readwrite");
      for (const [s, op, v] of ops) {
        const os = tx.objectStore(s);
        if (op === "put") os.put(v); else os.delete(v);
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error || new Error("تعذّر الحفظ"));
    });
  }

  const put = (s, v) => write([[s, "put", v]]);
  const del = (s, id) => write([[s, "del", id]]);
  const meta = (st) => [["meta", "put", { key: "settings", value: st.settings }],
    ["meta", "put", { key: "seq", value: st.seq }]];

  async function replaceAll(st) {
    if (fallback || !db) {
      localStorage.setItem(DB_NAME, JSON.stringify(root.Domain.toBackup(st)));
      return;
    }
    await new Promise((resolve, reject) => {
      const tx = db.transaction(STORES, "readwrite");
      for (const s of STORES) tx.objectStore(s).clear();
      for (const s of ["shops", "invoices", "vouchers", "held"]) {
        for (const v of st[s]) tx.objectStore(s).put(v);
      }
      tx.objectStore("meta").put({ key: "settings", value: st.settings });
      tx.objectStore("meta").put({ key: "seq", value: st.seq });
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  root.Store = { load, write, put, del, meta, replaceAll };
})(window);
