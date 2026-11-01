// يقارن معادلات الجوال بمعادلات البرنامج (حالات `parity_gen.py`).
const fs = require("fs");
const path = require("path");
const Num = require(path.join(__dirname, "../web/js/num.js"));
const Gold = require(path.join(__dirname, "../web/js/gold.js"));
const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const fn = {
  round: (x, n) => Num.pyRound(x, n),
  f2: (x) => Num.f2(x),
  f2nosep: (x) => Num.f2(x, { sep: false }),
  toBase: Gold.toBase, fromBase: Gold.fromBase, stonesAfter: Gold.stonesAfter,
  registered: Gold.registered, standing: Gold.standing,
  totalWages: Gold.totalWages, wagesVat: Gold.wagesVat,
  g: Gold.g, store: Gold.store, rate: Gold.rate, rateStore: Gold.rateStore,
  wageStore: Gold.wageStore,
  lineWages: (a, wage, k) => Gold.totalWages(Gold.wageStore(wage, k), Num.pyRound(Gold.store(a, k), 3)),
  voucherEquiv: (a, k) => Gold.voucherGold(a, k).equiv,
};
let bad = 0;
const seen = {};
for (const [name, args, want] of cases) {
  const got = fn[name](...args);
  const ok = typeof want === "string" ? got === want : Object.is(got, want) || got === want;
  seen[name] = (seen[name] || 0) + 1;
  if (!ok) {
    bad++;
    if (bad <= 15) console.log("✘", name, JSON.stringify(args), "python:", want, "js:", got);
  }
}
console.log(Object.entries(seen).map(([k, v]) => `${k}:${v}`).join(" "));
console.log(bad ? `✘ ${bad} اختلافاً من ${cases.length}` : `✔ ${cases.length} حالة مطابقة تماماً`);
process.exit(bad ? 1 : 0);
