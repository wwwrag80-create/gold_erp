// فحص منطق الجوال: الأرصدة والفواتير والسندات وكشف الحساب وحركة الطقم.
//   node mobile/tests/domain.test.js
const path = require("path");
const Num = require(path.join(__dirname, "../web/js/num.js"));
const G = require(path.join(__dirname, "../web/js/gold.js"));
const D = require(path.join(__dirname, "../web/js/domain.js"));

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log("  ✔", name); }
  else { fail++; console.log("  ✘", name, detail === undefined ? "" : "— " + JSON.stringify(detail)); }
}
function throws(fn, re) {
  try { fn(); return false; } catch (e) { return re ? re.test(e.message) : true; }
}

const st = D.newState();
const a = D.saveShop(st, { name: "محل الأمانة", phone: "0500000001", agreedWage18: 20 });
const b = D.saveShop(st, { name: "محل النخبة" });
check("المحل الجديد يُحفظ", st.shops.length === 2);
check("ولا يتكرّر الاسم", throws(() => D.saveShop(st, { name: "محل الأمانة" }), /بالاسم نفسه/));

// ── فاتورة بيع: سطران — أحدهما بعيار 21 وبأحجار ──
const e1 = { wo: "W100", model: "M1", karat: 18, gold: 10, small: 1, big: 2, wage: 20 };
Object.assign(e1, G.entryDerive(e1.gold, e1.small, e1.big, 0.5, false, 0));
const l1 = D.buildLine({ ...e1, reg: e1.reg, standing: e1.standing, after: e1.after });
check("الوزن المقيد = الذهب + الفصوص + الأحجار بعد الخصم (10 + 1 + 1)", l1.reg18 === 12, l1.reg18);
check("الأجرة = الأجر × المقيد", l1.wages === 240, l1.wages);
const l2 = D.buildLine({ wo: "W200", karat: 21, gold: 18, reg: 18, standing: 18, wage: 23 });
check("وزن عيار 21 يُخزَّن بمكافئ 18 (18 × 21 ÷ 18 = 21)", l2.reg18 === 21, l2.reg18);
check("وأجر 23 لجرام 21 يبقى أجرةً 414 ريالاً (23 × 18)", l2.wages === 414, l2.wages);
check("السطر المكرّر في الفاتورة يُرفض",
  throws(() => D.saveInvoice(st, { kind: "sale", shopId: a.id, lines: [l1, l1] }), /مكرّر/));
const s1 = D.saveInvoice(st, { kind: "sale", shopId: a.id, date: "2026-10-01", vat: true, lines: [l1, l2] });
check("رقم الفاتورة بصيغة البرنامج", s1.no === "S-00001", s1.no);
check("إجمالي الوزن 33 وأجور 654 وضريبة 98.10", s1.totalW18 === 33 && s1.wages === 654 && s1.vatAmt === 98.1,
  [s1.totalW18, s1.wages, s1.vatAmt]);
let bal = D.balance(st, a.id);
check("الفاتورة على المحل: 33 جم و752.10 ريال", bal.gold18 === 33 && bal.cash === 752.1, bal);

// ── مرتجع W100 — يُعبّأ من فاتورة البيع ──
let last = D.woLast(st, "W100");
check("آخر حركة لـW100 بيع بالفاتورة S-00001", last && last.kind === "sale" && last.inv.no === "S-00001");
const back = D.lineToEntry(last.line, 18);
check("تعبئة المرتجع بأوزان البيع نفسها", back.gold === 10 && back.small === 1 && back.big === 2 && back.reg === 12, back);
const r1 = D.saveInvoice(st, { kind: "sale_return", shopId: a.id, date: "2026-10-05",
  lines: [D.buildLine({ ...back, wage: back.wage })] });
check("رقم المرتجع R-00001", r1.no === "R-00001");
bal = D.balance(st, a.id);
check("المرتجع يُنقص 12 جم و240 ريال", bal.gold18 === 21 && bal.cash === 512.1, bal);

// ── بيع W100 من جديد لمحلٍّ آخر: الأوزان من المرتجع ──
last = D.woLast(st, "W100");
check("آخر حركة لـW100 الآن مرتجع", last && last.kind === "sale_return" && last.inv.no === "R-00001");
const again = D.lineToEntry(last.line, 21);
check("بعيار 21: الأوزان تُعرض محوّلة (12 جم 18 = 10.286 جم 21)", again.reg === 10.286, again.reg);
const s2line = D.buildLine({ ...again, karat: 21 });
check("ويعود المقيد للتخزين 12 مكافئ 18 بالضبط (لا 12.001)", s2line.reg18 === 12, s2line.reg18);
const typed = D.buildLine({ ...again, karat: 21, reg: 10 });
check("وما غيّره المستخدم يُعتمد كما كتبه", typed.reg18 === G.store(10, 21), typed.reg18);
const s2 = D.saveInvoice(st, { kind: "sale", shopId: b.id, date: "2026-10-06",
  lines: [D.buildLine({ ...D.lineToEntry(last.line, 18) })] });
check("بيعه لمحلٍّ آخر", s2.no === "S-00002" && D.woLast(st, "W100").shop.id === b.id);
check("حركة الطقم ثلاث: بيع · مرتجع · بيع",
  D.woHistory(st, "W100").map((m) => m.kind).join(",") === "sale,sale_return,sale");
check("رقم تشغيل غير مسجّل لا حركة له", D.woLast(st, "X999") === null);

// ── سند قبض: ذهب عيار 21 + نقد + خصم نقدي ──
const v1 = D.saveVoucher(st, { kind: "receipt", shopId: a.id, date: "2026-10-07",
  rows: [{ kind: "gold", weight: 6, karat: 21 }, { kind: "cash", amount: 500 }], discCash: 2.1 });
check("ذهب 6 جم عيار 21 = 7 جم مكافئ 18", v1.rows[0].equiv === 7, v1.rows[0].equiv);
check("رقم التحصيل RV-00001", v1.no === "RV-00001");
bal = D.balance(st, a.id);
check("بعد القبض: ذهب 14 ونقد 10.00", bal.gold18 === 14 && bal.cash === 10, bal);
check("الخصم في سند الصرف مرفوض",
  throws(() => D.saveVoucher(st, { kind: "payment", shopId: a.id, rows: [{ kind: "cash", amount: 5 }], discCash: 1 }), /التحصيل فقط/));
const p1 = D.saveVoucher(st, { kind: "payment", shopId: a.id, date: "2026-10-08",
  rows: [{ kind: "gold", weight: 2, karat: 18 }] });
bal = D.balance(st, a.id);
check("سند الصرف يزيد ما على المحل", p1.no === "PV-00001" && bal.gold18 === 16, bal);

// ── الرصيد عند المستند لا اليوم ──
const ar = D.balanceAround(st, s1);
check("رصيد الفاتورة الأولى: قبلها صفر وبعدها 33 — لا يدخل فيه ما جاء بعدها",
  ar.before.gold18 === 0 && ar.after.gold18 === 33 && ar.after.cash === 752.1, ar);
const av = D.balanceAround(st, v1);
check("ورصيد السند بعده 14 جم و10 ريال", av.after.gold18 === 14 && av.after.cash === 10, av);

// ── كشف الحساب ──
const stm = D.statement(st, a.id);
check("الكشف: أربع حركات والرصيد الأخير = الرصيد", stm.rows.length === 4 && stm.gold18 === 16 && stm.cash === 10,
  stm.rows.map((r) => [r.label, r.gbal, r.cbal]));
const part = D.statement(st, a.id, "2026-10-05", "2026-10-07");
check("من/إلى: رصيدٌ سابق ثم حركتا الفترة",
  part.rows.length === 3 && part.rows[0].kind === "prev" && part.rows[0].gbal === 33 && part.rows[2].gbal === 14,
  part.rows.map((r) => [r.label, r.gbal]));

// ── رصيدٌ افتتاحي ──
D.saveShop(st, { ...b, openGold18: -5, openCash: 100, openDate: "2026-09-01" });
const sb = D.statement(st, b.id);
check("الرصيد الافتتاحي أول سطرٍ في الكشف", sb.rows[0].kind === "opening" && sb.rows[0].gbal === -5, sb.rows[0]);
check("ثم البيع فوقه", sb.gold18 === 7 && sb.cash === 340, [sb.gold18, sb.cash]);

// ── تعديل الفاتورة يبقي رقمها، والحذف يلغي أثرها ──
const edited = D.saveInvoice(st, { ...s2, lines: [...s2.lines, D.buildLine({ wageOnly: true, amount: 50 })] });
check("التعديل يبقي الرقم ويضيف «أجر فقط»", edited.no === "S-00002" && edited.wages === 290, [edited.no, edited.wages]);
check("ولا يتغيّر نوعها", throws(() => D.saveInvoice(st, { ...s2, kind: "sale_return" }), /نوع الفاتورة/));
D.deleteInvoice(st, edited.id);
check("الحذف يلغي أثرها", D.balance(st, b.id).gold18 === -5);

// ── النسخة الاحتياطية ──
const bk = JSON.parse(JSON.stringify(D.toBackup(st)));
const st2 = D.fromBackup(bk);
check("الاسترجاع يعيد البيانات والأرصدة كما هي",
  st2.invoices.length === st.invoices.length && D.balance(st2, a.id).gold18 === 16 && st2.seq.S === 2);
check("وملفٌ غريب يُرفض", throws(() => D.fromBackup({ foo: 1 }), /ليس نسخة/));

// ── شاشة العملاء (المبيعات والسداد) ولوحة التحكم ──
{
  const t3 = D.newState();
  const A = D.saveShop(t3, { name: "أ" });
  const Bs = D.saveShop(t3, { name: "ب" });
  const t0 = D.today();
  const curM = t0.slice(0, 7);
  const pd = new Date(+t0.slice(0, 4), +t0.slice(5, 7) - 2, 1);
  const prevM = `${pd.getFullYear()}-${String(pd.getMonth() + 1).padStart(2, "0")}`;
  const ln = (wo, reg) => D.buildLine({ wo, karat: 18, gold: reg, reg, standing: reg, wage: 10 });
  D.saveInvoice(t3, { kind: "sale", shopId: A.id, date: prevM + "-10", lines: [ln("X1", 10)] });
  D.saveInvoice(t3, { kind: "sale", shopId: A.id, date: curM + "-01", lines: [ln("X2", 20)] });
  const x1 = D.woLast(t3, "X1");
  D.saveInvoice(t3, { kind: "sale_return", shopId: A.id, date: curM + "-01",
    lines: [D.buildLine(D.lineToEntry(x1.line, 18))] });
  D.saveVoucher(t3, { kind: "receipt", shopId: A.id, date: curM + "-01",
    rows: [{ kind: "gold", weight: 15, karat: 18 }, { kind: "cash", amount: 100 }] });

  const bm = D.board(t3, curM + "-01", null);
  const ra = bm.rows.find((r) => r.id === A.id), rb = bm.rows.find((r) => r.id === Bs.id);
  check("العملاء: الرصيد السابق 10 ومبيعات 20 ومرتجع 10 وسداد 15 — الباقي 5",
    ra.gold.open === 10 && ra.gold.sales === 20 && ra.gold.returns === 10 && ra.gold.paid === 15 &&
    ra.gold.net === 20 && ra.gold.remaining === 5, ra.gold);
  check("نسبة السداد 75% فالتقدير «جيد»، ونسبة المرتجع 33.3%",
    ra.gold.paidPct === 75 && ra.gold.grade === "جيد" && ra.gold.retPct === 33.3, ra.gold);
  check("والنقد: سداد 50% فالتقدير «مقبول» والباقي 100",
    ra.cash.paidPct === 50 && ra.cash.grade === "مقبول" && ra.cash.remaining === 100, ra.cash);
  check("ومن لا حركة له يُخفى", D.hasMovement(ra) && !D.hasMovement(rb) && rb.gold.grade === "—");
  check("الإجماليات = مجموع العملاء", bm.gold.paid === 15 && bm.gold.remaining === 5 && bm.cash.sales === 200, bm.gold);
  const all = D.board(t3, null, null).rows.find((r) => r.id === A.id);
  check("منذ البداية: لا رصيد سابق والمبيعات 30", all.gold.open === 0 && all.gold.sales === 30 && all.gold.remaining === 5, all.gold);
  check("الأعلى سداداً أولاً", bm.rows[0].id === A.id);
  check("التقدير بحدوده: 80 ممتاز · 60 جيد · 40 مقبول · دونها سيء · لا باقٍ مسدَّد",
    D.grade(80, 1, true, 1) === "ممتاز" && D.grade(60, 1, true, 1) === "جيد" && D.grade(40, 1, true, 1) === "مقبول" &&
    D.grade(39.9, 1, true, 1) === "سيء" && D.grade(100, 0, true, 5) === "مسدَّد");

}

// ══ المندوب: المصانع، البضاعة، التحصيل، الدفع، والممتلكات ══
{
  const t = D.newState();
  const shopA = D.saveShop(t, { name: "محل السلام" });
  const fac = D.saveShop(t, { name: "مصنع الريان", type: "factory", openGold18: -50, openCash: -1000, openDate: "2026-01-01" });
  check("المصنع يُحفظ بنوعه", D.isFactory(fac) && !D.isFactory(shopA) && D.factoriesOnly(t).length === 1 && D.shopsOnly(t).length === 1);
  check("ولا يتحوّل المحل مصنعاً", throws(() => D.saveShop(t, { ...shopA, type: "factory" }), /لا يتحوّل/));
  check("رصيده الافتتاحي: عليّ 50 جم و1000 ريال", D.balance(t, fac.id).gold18 === -50 && D.balance(t, fac.id).cash === -1000);

  // الطقم بلا اسم: الوزن وحده يكفي
  const plain = D.buildLine({ karat: 21, reg: 10, standing: 10, wage: 10 });
  check("سطرٌ بلا اسم طقم يُقبل (10 جم عيار 21)", plain.wo === "" && plain.reg18 === G.store(10, 21) && plain.lid);
  check("وسطران بلا اسم في فاتورةٍ واحدة لا يُعدّان تكراراً", !throws(() => D.checkLines([plain, D.buildLine({ reg: 5, wage: 1 })])));
  check("لكن الوزن لازم", throws(() => D.buildLine({ reg: 0, wage: 5 }), /أدخل الوزن/));

  // بضاعة من المصنع: طقمان، أحدهما بلا اسم
  const pin = D.saveInvoice(t, { kind: "purchase", shopId: fac.id, date: "2026-02-01",
    lines: [D.buildLine({ wo: "T1", reg: 20, wage: 5 }), D.buildLine({ reg: 12, wage: 5 })] });
  check("رقمها P-00001", pin.no === "P-00001", pin.no);
  check("البضاعة تُرحَّل للمصنع على المحل؟ لا — المحل مرفوض", throws(() => D.saveInvoice(t, { kind: "purchase", shopId: shopA.id, lines: [plain] }), /اختر المصنع/));
  check("والبيع لا يُرحَّل على مصنع", throws(() => D.saveInvoice(t, { kind: "sale", shopId: fac.id, lines: [plain] }), /اختر المحل/));
  let fb = D.balance(t, fac.id);
  check("عليّ للمصنع: 50 + 32 = 82 جم، و1000 + 160 = 1160 ريال", fb.gold18 === -82 && fb.cash === -1160, fb);
  let hd = D.holdings(t);
  check("الطقمان في يدي من المصنع", hd.pieces.length === 2 && hd.pieces.every((p) => p.party.id === fac.id) && hd.setsW18 === 32, hd.pieces.map((p) => p.name));

  // بيع الطقم المسمّى بالاسم، وغير المسمّى باختياره من الممتلكات
  const unnamed = hd.pieces.find((p) => !p.name);
  const s1 = D.saveInvoice(t, { kind: "sale", shopId: shopA.id, date: "2026-02-02",
    lines: [D.buildLine({ wo: "T1", reg: 20, wage: 12 }), D.buildLine({ reg: 12, wage: 12, src: unnamed.id })] });
  hd = D.holdings(t);
  check("بعد بيعهما لا طقم في يدي", hd.pieces.length === 0, hd.pieces);
  check("والمحل عليه 32 جم و384 ريال", D.balance(t, shopA.id).gold18 === 32 && D.balance(t, shopA.id).cash === 384);
  check("الطقم المختار لا يُضاف مرتين", throws(() => D.checkLines([D.buildLine({ reg: 1, src: "x" }), D.buildLine({ reg: 2, src: "x" })]), /مرتين/));

  // مرتجعٌ من المحل يعود إلى يدي
  D.saveInvoice(t, { kind: "sale_return", shopId: shopA.id, date: "2026-02-03", lines: [D.buildLine({ wo: "T1", reg: 20, wage: 12 })] });
  hd = D.holdings(t);
  check("المرتجع T1 في يدي، من «محل السلام»", hd.pieces.length === 1 && hd.pieces[0].name === "T1" && hd.pieces[0].party.id === shopA.id);
  check("وحركته: بضاعة · بيع · مرتجع", D.woHistory(t, "T1").map((m) => m.kind).join(",") === "purchase,sale,sale_return");
  // إرجاعه للمصنع يخرجه من يدي ويُنقص ما عليّ
  const pr = D.saveInvoice(t, { kind: "purchase_return", shopId: fac.id, date: "2026-02-04", lines: [D.buildLine({ wo: "T1", reg: 20, wage: 5 })] });
  hd = D.holdings(t);
  fb = D.balance(t, fac.id);
  check("إرجاع لمصنع PR-00001: خرج من يدي، وعليّ 62 جم و1060 ريال",
    pr.no === "PR-00001" && hd.pieces.length === 0 && fb.gold18 === -62 && fb.cash === -1060, fb);

  // التحصيل من المحل يملأ صناديقي، والدفع للمصنع يُنقصها
  const rv = D.saveVoucher(t, { kind: "receipt", shopId: shopA.id, date: "2026-02-05",
    rows: [{ kind: "gold", weight: 10, karat: 21 }, { kind: "gold", weight: 3, karat: 18 }, { kind: "cash", amount: 200 }] });
  check("التحصيل رقمه RV-00001 ولا يكون من مصنع", rv.no === "RV-00001" &&
    throws(() => D.saveVoucher(t, { kind: "receipt", shopId: fac.id, rows: [{ kind: "cash", amount: 1 }] }), /اختر المحل/));
  hd = D.holdings(t);
  const b21 = hd.boxes.find((b) => b.karat === 21), b18 = hd.boxes.find((b) => b.karat === 18);
  check("صندوق 21: 10 جم من «محل السلام» بتاريخه", b21 && b21.weight === 10 && b21.moves[0].party.id === shopA.id && b21.moves[0].date === "2026-02-05");
  check("صندوق 18: 3 جم، والنقد 200", b18 && b18.weight === 3 && hd.cash.amount === 200);
  check("الصناديق مرتّبة بالعيار الأعلى أولاً", hd.boxes[0].karat === 21);
  const pv = D.saveVoucher(t, { kind: "payment", shopId: fac.id, date: "2026-02-06",
    rows: [{ kind: "gold", weight: 6, karat: 21 }, { kind: "cash", amount: 150 }] });
  hd = D.holdings(t);
  fb = D.balance(t, fac.id);
  check("الدفع للمصنع PV-00001: صندوق 21 بقي 4 جم والنقد 50",
    pv.no === "PV-00001" && hd.boxes.find((b) => b.karat === 21).weight === 4 && hd.cash.amount === 50, hd.cash);
  check("وحركة الصندوق: دفعٌ لـ«مصنع الريان» أولاً ثم التحصيل", hd.boxes[0].moves[0].sign === -1 && hd.boxes[0].moves[0].party.id === fac.id);
  check("ونقص ما عليّ للمصنع: 6 جم عيار 21 = 7 جم مكافئ 18 → 55 جم، و910 ريال", fb.gold18 === -55 && fb.cash === -910, fb);
  check("ذهب الممتلكات بمكافئ 18: 4 × 21/18 + 3 = 7.667", hd.gold18 === 7.667, hd.gold18);
  check("المبيعات والتحصيل للمحلات وحدها", D.board(t, null, null).rows.length === 1);
}

// ══ الصورة والماس وكشف الماس ══
{
  const t = D.newState();
  const sh = D.saveShop(t, { name: "محل الماس" });
  const fa = D.saveShop(t, { name: "مصنع الماس", type: "factory" });
  const li = D.buildLine({ wo: "D1", reg: 10, wage: 5, diamond: 0.5, photo: "ph_abc" });
  check("السطر يحمل صورته وماسه", li.photo === "ph_abc" && li.diamond === 0.5);
  check("والتعبئة منه تنقل الصورة", D.lineToEntry(li, 18).photos.join() === "ph_abc");
  // أكثر من صورة للطقم: بلا تكرار، والأولى في `photo` كما كانت
  const lm = D.buildLine({ wo: "D3", reg: 5, wages: 10, photos: ["ph_1", "ph_2", "ph_1", "", "ph_3"] });
  check("صورٌ عدة للطقم: ph_1 · ph_2 · ph_3 بلا تكرار، والأولى صورته", lm.photos.join() === "ph_1,ph_2,ph_3" && lm.photo === "ph_1");
  check("والتعبئة منه تنقلها كلها", D.lineToEntry(lm, 18).photos.join() === "ph_1,ph_2,ph_3");
  check("سطرٌ قديم بصورةٍ واحدة يُقرأ صوراً", D.linePhotos({ wo: "Q", reg18: 1, photo: "ph_old" }).join() === "ph_old" &&
    D.linePhotos({ wageOnly: true, photo: "x" }).length === 0 && D.linePhotos({ reg18: 1 }).length === 0);
  check("حتى 10 صور للطقم", D.buildLine({ reg: 1, wages: 1, photos: Array.from({ length: 14 }, (_, i) => "p" + i) }).photos.length === D.MAX_PHOTOS);
  const dph = D.docPhotos({ lines: [lm, D.buildLine({ reg: 2, wages: 1 }), D.buildLine({ wo: "D4", reg: 1, wages: 1, photo: "ph_9" })] });
  check("صور الفاتورة كلٌّ بطقمه: D3 ×3 ثم D4 (السطر 3)", dph.map((x) => `${x.wo}:${x.id}:${x.n}`).join() === "D3:ph_1:1,D3:ph_2:1,D3:ph_3:1,D4:ph_9:3");
  D.saveInvoice(t, { kind: "purchase", shopId: fa.id, date: "2026-03-01", lines: [D.buildLine({ wo: "D1", reg: 10, wage: 5, diamond: 0.5 }),
    D.buildLine({ wo: "D2", reg: 8, wage: 5, diamond: 0.25 })] });
  D.saveInvoice(t, { kind: "sale", shopId: sh.id, date: "2026-03-02", lines: [D.buildLine({ wo: "D1", reg: 10, wage: 9, diamond: 0.5 }),
    D.buildLine({ wo: "D2", reg: 8, wage: 9, diamond: 0.25 })] });
  D.saveInvoice(t, { kind: "sale_return", shopId: sh.id, date: "2026-03-05", lines: [D.buildLine({ wo: "D2", reg: 8, wage: 9, diamond: 0.25 })] });
  D.saveInvoice(t, { kind: "sale", shopId: sh.id, date: "2026-03-06", lines: [D.buildLine({ reg: 3, wage: 9 })] });
  const ds = D.diamondStatement(t, sh.id);
  check("كشف الماس للمحل: بيع 0.75 · مرتجع 0.25 · صافي 0.50 — وفاتورةٌ بلا ماس لا تظهر",
    ds.rows.length === 2 && ds.plus === 0.75 && ds.minus === 0.25 && ds.diamond === 0.5, ds);
  check("وأطقم كل فاتورة بماسها", ds.rows[0].sets.map((x) => `${x.name}:${x.diamond}`).join() === "D1:0.5,D2:0.25");
  const dp = D.diamondStatement(t, sh.id, "2026-03-03", null);
  check("من تاريخ: رصيدٌ سابق 0.75 ثم المرتجع", dp.rows[0].kind === "prev" && dp.rows[0].bal === 0.75 && dp.diamond === 0.5, dp.rows);
  const df = D.diamondStatement(t, fa.id);
  check("وللمصنع: البضاعة سالبة كالذهب (−0.75)", df.diamond === -0.75 && df.minus === 0.75);
  check("الماس لا يدخل رصيد الذهب", D.balance(t, sh.id).gold18 === 13);
  const bk = D.toBackup(t, { ph_ok: "data:image/jpeg;base64,AAAA", "../x": "data:image/jpeg;base64,AA", ph_bad: "javascript:1" });
  const got = D.backupPhotos(JSON.parse(JSON.stringify(bk)));
  check("الصور في ملف النسخة — والاسم الغريب أو المحتوى غير الصورة يُرفض", Object.keys(got).join() === "ph_ok");
  check("ونسخةٌ بلا صور سليمة", Object.keys(D.backupPhotos(D.toBackup(t))).length === 0);
}

// ══ الأجور مبلغٌ مباشر، والسطر: ذهبٌ أو ماسٌ أو أجورٌ وحدها ══
{
  const a = D.buildLine({ wo: "W", reg: 12.345, wages: 333.333 });
  check("الأجور تُكتب مبلغاً وتُعتمد كما هي (333.33)", a.wages === 333.33 && !a.wageOnly && a.reg18 === 12.345, a.wages);
  const d = D.buildLine({ diamond: 0.4 });
  check("ماسٌ وحده: سطرٌ بلا وزن", !d.wageOnly && d.reg18 === 0 && d.diamond === 0.4 && d.wages === 0);
  const w = D.buildLine({ wages: 75, wo: "تلميع" });
  check("أجورٌ وحدها: سطر «أجور فقط» ببيانه", w.wageOnly && w.amount === 75 && w.note === "تلميع");
  const g = D.buildLine({ reg: 3 });
  check("ذهبٌ وحده: بلا أجور", !g.wageOnly && g.reg18 === 3 && g.wages === 0);
  check("والسطر الفارغ مرفوض", throws(() => D.buildLine({ wages: 0 }), /الوزن أو الأجور أو الماس/));
  const t = D.newState();
  const sh = D.saveShop(t, { name: "م" });
  const inv = D.saveInvoice(t, { kind: "sale", shopId: sh.id, lines: [d, w, g] });
  check("وتُرحَّل معاً: وزن 3 وأجور 75 وماس 0.4", inv.totalW18 === 3 && inv.wages === 75 && D.diamondOf(inv) === 0.4);
  check("والحساب: 3 جم و75 ريال عليه", D.balance(t, sh.id).gold18 === 3 && D.balance(t, sh.id).cash === 75);
}

// ══ الممتلكات: ذهب المصانع عندي، وذهبي عند العملاء ══
{
  const t = D.newState();
  const f1 = D.saveShop(t, { name: "مصنع أ", type: "factory", openGold18: -10, openDate: "2026-01-01" });
  const f2_ = D.saveShop(t, { name: "مصنع ب", type: "factory" });
  const c1 = D.saveShop(t, { name: "عميل أ" });
  const c2 = D.saveShop(t, { name: "عميل ب" });
  D.saveInvoice(t, { kind: "purchase", shopId: f1.id, date: "2026-02-01", lines: [D.buildLine({ reg: 30, wages: 90 })] });
  D.saveInvoice(t, { kind: "purchase_return", shopId: f1.id, date: "2026-02-02", lines: [D.buildLine({ reg: 5, wages: 15 })] });
  D.saveInvoice(t, { kind: "purchase", shopId: f2_.id, date: "2026-02-01", lines: [D.buildLine({ reg: 8, wages: 0 })] });
  D.saveVoucher(t, { kind: "payment", shopId: f1.id, date: "2026-02-03", rows: [{ kind: "gold", weight: 6, karat: 18 }, { kind: "cash", amount: 50 }] });
  D.saveInvoice(t, { kind: "sale", shopId: c1.id, date: "2026-02-04", lines: [D.buildLine({ reg: 20, wages: 200 })] });
  D.saveInvoice(t, { kind: "sale", shopId: c2.id, date: "2026-02-04", lines: [D.buildLine({ reg: 4, wages: 40 })] });
  D.saveVoucher(t, { kind: "receipt", shopId: c2.id, date: "2026-02-05", rows: [{ kind: "gold", weight: 6, karat: 18 }] });
  const ex = D.exposure(t);
  const a = ex.factories.find((x) => x.party.id === f1.id);
  check("مصنع أ: أخذتُ 30 · أرجعتُ 5 · سدّدتُ 6 — وعليّ 10 + 30 − 5 − 6 = 29", a.took18 === 30 && a.back18 === 5 && a.paid18 === 6 && a.owe18 === 29, a);
  check("وعليّ له نقداً 90 − 15 − 50 = 25", a.oweCash === 25, a.oweCash);
  check("ذهب المصانع عندي: 29 + 8 = 37 — الأكثر أولاً", ex.facGold18 === 37 && ex.factories[0].party.id === f1.id && ex.facCash === 25);
  const b = ex.customers.find((x) => x.party.id === c2.id);
  check("عميل ب دفع أكثر مما أخذ: له 2 — فلا يُحسب في «عند العملاء»", b.gold18 === -2 && ex.cusGold18 === 20 && ex.cusCash === 240, ex);
}

// ══ البحث عن طقم: باسمه أو وزنه — ومع من هو الآن (1.6) ══
{
  const t = D.newState();
  const f = D.saveShop(t, { name: "مصنع الريان", type: "factory" });
  const c = D.saveShop(t, { name: "محل الأمانة" });
  const c2 = D.saveShop(t, { name: "مجوهرات النخبة" });
  const p = D.saveInvoice(t, { kind: "purchase", shopId: f.id, date: "2026-03-01", lines: [
    D.buildLine({ wo: "ط-101", reg: 24.5, wages: 490, photos: ["ph1", "ph2"] }),
    D.buildLine({ wo: "ط-102", reg: 18.75, wages: 375 }),
    D.buildLine({ wo: "خاتم 7", karat: 21, reg: 6, wages: 60 }),
    D.buildLine({ reg: 50, wages: 1000, photos: ["inv"] })] });
  const bulkId = p.lines[3].lid;
  D.saveInvoice(t, { kind: "sale", shopId: c.id, date: "2026-03-02", lines: [D.buildLine({ wo: "ط-101", reg: 24.5, wages: 600 })] });
  D.saveInvoice(t, { kind: "purchase_return", shopId: f.id, date: "2026-03-03", lines: [D.buildLine({ wo: "ط-102", reg: 18.75, wages: 375 })] });
  D.saveInvoice(t, { kind: "sale", shopId: c2.id, date: "2026-03-04", lines: [D.buildLine({ reg: 50, wages: 900, src: bulkId })] });
  // بيعٌ بالوزن مباشرةً (بلا اسمٍ ولا طقمٍ مختار) — ليس طقماً يُتتبَّع
  D.saveInvoice(t, { kind: "sale", shopId: c.id, date: "2026-03-05", lines: [D.buildLine({ reg: 10, wages: 250 })] });
  const names = (r) => r.map((x) => x.name || "بلا اسم").join("،");
  const r1 = D.searchSets(t, "ط");
  check("من أول حرف: «ط» ⇒ الطقمان ط-101 وط-102 (الأحدث حركةً أولاً)", names(r1) === "ط-102،ط-101", names(r1));
  const a = D.searchSets(t, "ط-101")[0];
  check("ط-101: عند «محل الأمانة» — مباعٌ بالفاتورة S-00001", a.where === "customer" && a.party.id === c.id && a.last.inv.no === "S-00001", a.where);
  check("وحركتاه: بضاعة ثم بيع، ووزنه 24.50 عيار 18 وصورتاه", a.moves.map((m) => m.kind).join(",") === "purchase,sale" &&
    a.weight === 24.5 && a.karat === 18 && a.photos.join() === "ph1,ph2");
  check("ط-102 رجع إلى المصنع", D.searchSets(t, "ط-102")[0].where === "factory");
  check("بلا مسافةٍ ولا شَرطة وبأرقامٍ عربية: «ط١٠١» = ط-101", names(D.searchSets(t, "ط١٠١")) === "ط-101");
  check("وجزءٌ من الاسم: «101» يجد ط-101", names(D.searchSets(t, "101")) === "ط-101");
  check("الألف والتاء: «خاتم ٧» و«خاتم7»", names(D.searchSets(t, "خاتم ٧")) === "خاتم 7" && names(D.searchSets(t, "خاتم7")) === "خاتم 7");
  check("وعياره 21 بوزنه بعياره: 6.00", D.searchSets(t, "خاتم")[0].weight === 6 && D.searchSets(t, "خاتم")[0].karat === 21);
  const w = D.searchSets(t, "24.5");
  check("بالوزن: «24.5» ⇒ ط-101 (24.50)", names(w) === "ط-101", names(w));
  check("وبأول الرقم: «18» ⇒ ط-102 (18.75)", names(D.searchSets(t, "18")) === "ط-102");
  const u = D.searchSets(t, "50");
  check("والطقم بلا اسم بوزنه 50 — بيع من الأطقم التي معي ⇒ عند «مجوهرات النخبة»",
    u.length === 1 && !u[0].name && u[0].where === "customer" && u[0].party.id === c2.id && u[0].photos.join() === "inv", names(u));
  check("والبيع بالوزن مباشرةً (10 جم) ليس طقماً", D.searchSets(t, "10").every((x) => x.name), names(D.searchSets(t, "10")));
  check("الاسم المطابق تماماً قبل ما يحويه", D.searchSets(t, "ط-101")[0].name === "ط-101");
  check("ولا نتائج لنصٍّ فارغ أو غير مطابق", D.searchSets(t, "  ").length === 0 && D.searchSets(t, "س").length === 0);
  // يعود الطقم إلى اليد بمرتجعٍ من العميل
  D.saveInvoice(t, { kind: "sale_return", shopId: c.id, date: "2026-03-06", lines: [D.buildLine({ wo: "ط-101", reg: 24.5, wages: 600 })] });
  check("بعد المرتجع: ط-101 معك", D.searchSets(t, "ط-101")[0].where === "in");
}

console.log(`\n${fail ? "✘" : "✔"} ${pass} نجح · ${fail} فشل`);
process.exit(fail ? 1 : 0);
