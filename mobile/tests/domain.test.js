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
check("رقم السند RV-00001", v1.no === "RV-00001");
bal = D.balance(st, a.id);
check("بعد القبض: ذهب 14 ونقد 10.00", bal.gold18 === 14 && bal.cash === 10, bal);
check("الخصم في سند الصرف مرفوض",
  throws(() => D.saveVoucher(st, { kind: "payment", shopId: a.id, rows: [{ kind: "cash", amount: 5 }], discCash: 1 }), /القبض فقط/));
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

console.log(`\n${fail ? "✘" : "✔"} ${pass} نجح · ${fail} فشل`);
process.exit(fail ? 1 : 0);
