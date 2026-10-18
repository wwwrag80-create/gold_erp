# -*- coding: utf-8 -*-
"""حركة الطقم المنظّمة (4.75): بيع ← مرتجع ← بيع ← مرتجع …

الطقم المفرد قطعةٌ واحدة: لا يخرج مرتين قبل أن يعود، ولا يعود قبل أن
يخرج. فحركاته **تتناوب** دائماً، وحالته اليوم (في الخزنة أو عند
المندوب) هي نتيجة آخر حلقةٍ في هذه السلسلة.

**الخلل الذي تعالجه**: كانت الحركات تُرتَّب بالتاريخ ثم بمعرّف الفاتورة.
والعمليات التي تُعيد إنشاء فاتورة (نقلها لجهة أخرى · تعديل بنودها ·
عكس نوعها) تمنح الفاتورة معرّفاً جديداً أكبر بتاريخها القديم نفسه —
فتقفز فوق حركات اليوم نفسه التي سبقتها فعلاً: بيعٌ يوم 10 ثم مرتجعٌ
وبيعٌ يوم 11 يُقرأ «بيع · بيع · مرتجع»، ويُحسب الطقم في الخزنة وهو عند
المندوب. وتلك العمليات وحذف الفاتورة كانت تكتب الحالة مباشرةً بلا
نظرٍ إلى ما بعدها.

**المعالجة**:
  · ترتيبٌ واحد لكل الشاشات: بالتاريخ، وحركات اليوم الواحد تُرتَّب بما
    يحفظ التناوب ابتداءً من حالة الطقم قبل ذلك اليوم.
  · الحالة **تُشتقّ** من السلسلة كاملةً بعد كل عملية تمسّ الفواتير
    (`resync`)، لا من آخر معرّف.
  · فحصٌ عند الإقلاع يصحّح ما فسد من قبل ويسجّله في سجل العمليات.

الرقم التجميعي رصيدٌ وزني لا قطعة — خارج هذا كله، وكذلك الطقم الخدمي.
"""
from itertools import groupby

from services.audit import log_action

SALE, RETURN = "sale", "sale_return"
IN_STOCK, SOLD = "in_stock", "sold"
LABEL = {IN_STOCK: "في الخزنة", SOLD: "عند المندوب"}


def _after(kind):
    return SOLD if kind == SALE else IN_STOCK


def _start(moves):
    """حالة الطقم قبل أول حركة (`moves` مرتّبة بالتاريخ).

    الأصل أن يُولد في الخزنة. ويُولد «مباعاً» إن أُدخل ليُرتجع (طقمٌ عند
    عميل لم تُسجَّل فاتورة خروجه — `create_return_stub`): وعلامته أن
    مرتجعاته أكثر من مبيعاته، أو أن يومه الأول مرتجعٌ بلا بيع.
    """
    sales = sum(1 for m in moves if m["kind"] == SALE)
    rets = len(moves) - sales
    if rets > sales:
        return SOLD
    if sales > rets or not moves:
        return IN_STOCK
    first = moves[0]["date"]
    return IN_STOCK if any(m["kind"] == SALE for m in moves
                           if m["date"] == first) else SOLD


def _by_date(moves):
    return sorted(moves, key=lambda m: (m["date"] or "", m["id"]))


def order(moves):
    """الحركات بترتيبها الحقيقي: بالتاريخ، وفي اليوم الواحد بالتناوب.

    `moves`: [{"id", "kind", "date"}] بأي ترتيب. في كل يوم تُختار الحركة
    التي تسمح بها الحالة (في الخزنة ← بيع · عند المندوب ← مرتجع)، وبين
    المتماثلة يُقدَّم الأقدم إصداراً. وإن لم توجد (بيانات قديمة شاذة)
    أُخذت الأقدم كما هي — فلا تضيع حركة.
    """
    moves = _by_date(moves)
    state = _start(moves)
    out = []
    for _d, day in groupby(moves, key=lambda m: m["date"] or ""):
        left = list(day)
        while left:
            want = SALE if state == IN_STOCK else RETURN
            pick = next((m for m in left if m["kind"] == want), left[0])
            left.remove(pick)
            out.append(pick)
            state = _after(pick["kind"])
    return out


def final_state(moves):
    """حالة الطقم بعد سلسلته — `None` لطقمٍ بلا حركة (تبقى كما هي)."""
    seq = order(moves)
    return _after(seq[-1]["kind"]) if seq else None


_MOVES_SQL = (
    "SELECT DISTINCT it.work_order_id wid, i.id, i.kind, i.invoice_date date"
    " FROM invoice_items it JOIN invoices i ON i.id=it.invoice_id"
    " WHERE i.is_deleted=0 AND i.kind IN ('sale','sale_return')")


def moves_of(conn, wo_id):
    return [dict(r) for r in conn.execute(
        _MOVES_SQL + " AND it.work_order_id=?", (int(wo_id),))]


def ordered_ids(conn, wo_id):
    """معرّفات فواتير الطقم بترتيبها الحقيقي."""
    return [m["id"] for m in order(moves_of(conn, wo_id))]


def is_last(conn, wo_id, invoice_id):
    """هل الفاتورة آخر حركةٍ للطقم في سلسلته المنظّمة؟"""
    ids = ordered_ids(conn, wo_id)
    return not ids or ids[-1] == int(invoice_id)


def resync(conn, wo_ids=None, username="system"):
    """يضبط حالة كل طقمٍ مفرد على نتيجة سلسلته — ويسجّل ما صُحِّح.

    `wo_ids=None` ← كل الأطقم (فحص الإقلاع). يُعيد [(رقم التشغيل، من، إلى)].
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(work_orders)")}
    where = "COALESCE(w.is_bulk,0)=0"
    if "is_service" in cols:
        where += " AND COALESCE(w.is_service,0)=0"
    params = []
    if wo_ids is not None:
        ids = sorted({int(i) for i in wo_ids if i})
        if not ids:
            return []
        where += f" AND w.id IN ({','.join('?' * len(ids))})"
        params = ids
    wos = {r["id"]: r for r in conn.execute(
        "SELECT w.id, w.work_order_no, w.status FROM work_orders w"
        f" WHERE w.is_deleted=0 AND {where}", params)}
    if not wos:
        return []
    sql, args = _MOVES_SQL, []
    if wo_ids is not None:
        sql += f" AND it.work_order_id IN ({','.join('?' * len(wos))})"
        args = list(wos)
    by = {}
    for r in conn.execute(sql, args):
        if r["wid"] in wos:
            by.setdefault(r["wid"], []).append(dict(r))
    fixed = []
    for wid, mv in by.items():
        want = final_state(mv)
        w = wos[wid]
        if want and want != w["status"]:
            conn.execute("UPDATE work_orders SET status=? WHERE id=?",
                         (want, wid))
            log_action(conn, username, "resync", "work_orders", wid,
                       f"حالة الطقم {w['work_order_no']}: "
                       f"{LABEL.get(w['status'], w['status'])} ← "
                       f"{LABEL[want]} — من تسلسل حركته")
            fixed.append((w["work_order_no"], w["status"], want))
    return fixed
