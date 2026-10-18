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


def order(moves, start=None):
    """الحركات بترتيبها الحقيقي: بالتاريخ، وفي اليوم الواحد بالتناوب.

    `moves`: [{"id", "kind", "date"}] بأي ترتيب. في كل يوم تُختار الحركة
    التي تسمح بها الحالة (في الخزنة ← بيع · عند المندوب ← مرتجع)، وبين
    المتماثلة يُقدَّم الأقدم إصداراً. وإن لم توجد (بيانات قديمة شاذة)
    أُخذت الأقدم كما هي — فلا تضيع حركة.
    """
    moves = _by_date(moves)
    state = start or _start(moves)
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


def final_state(moves, start=None):
    """حالة الطقم بعد سلسلته — `None` لطقمٍ بلا حركة (تبقى كما هي)."""
    seq = order(moves, start)
    return _after(seq[-1]["kind"]) if seq else None


def violations(moves, start=None):
    """الحركات التي تكسر التناوب في سلسلتها المنظّمة (بيعان أو مرتجعان
    متتاليان) — تُعاد بأعيانها."""
    seq = order(moves, start)
    state = start or _start(_by_date(moves))
    bad = []
    for m in seq:
        if m["kind"] != (SALE if state == IN_STOCK else RETURN):
            bad.append(m)
        state = _after(m["kind"])
    return bad


_NEW = 10 ** 15            # معرّف حركةٍ لم تُحفظ بعد — آخر يومها


def birth(wo):
    """حالة الطقم يوم وُلد: المُورَّد (له قيد توريد) في الخزنة يقيناً؛ وما
    سواه (مُدخَلٌ ليُرتجع · بياناتٌ قديمة) يُستدلّ عليه من حركته."""
    try:
        return IN_STOCK if wo["entry_id"] else None
    except (KeyError, IndexError):
        return None


def _wo(conn, wo_id):
    return conn.execute("SELECT * FROM work_orders WHERE id=?",
                        (int(wo_id),)).fetchone()


def can_add(conn, wo, kind, date):
    """هل تستقيم السلسلة إن أُضيفت هذه الحركة بهذا التاريخ؟

    بلا حركاتٍ سابقة: الطقم المُورَّد يُولد في الخزنة، والمُدخَل ليُرتجع
    (بلا قيد توريد) حالته كما سُجّلت. ومع حركات: تُدرج الجديدة في يومها
    ويُنظر أتكسر التناوب أم لا — فالبيع بتاريخٍ قديم قبل مرتجعٍ لاحق
    يُرفض كما يُرفض بيع ما هو عند المندوب.
    """
    import datetime as _dt
    mv = moves_of(conn, wo["id"])
    if not mv:
        state = IN_STOCK if wo["entry_id"] else wo["status"]
        return kind == (SALE if state == IN_STOCK else RETURN)
    new = {"id": _NEW, "kind": kind,
           "date": str(date or _dt.date.today().isoformat())[:10]}
    b = birth(wo)
    before = {m["id"] for m in violations(mv, b)}
    after = {m["id"] for m in violations(mv + [new], b)}
    # لا هي تكسر التناوب ولا تكسره لحركةٍ بعدها كانت سليمة
    return _NEW not in after and after <= before


def _singles(conn, wo_ids):
    """الأطقم المفردة من بين هذه — لا التجميعي ولا الطقم الخدمي «أجر»
    (كلاهما يُباع مراراً بطبيعته فلا تناوب له)."""
    ids = sorted({int(i) for i in wo_ids if i})
    if not ids:
        return []
    cols = {r[1] for r in conn.execute("PRAGMA table_info(work_orders)")}
    svc = " AND COALESCE(is_service,0)=0" if "is_service" in cols else ""
    return [r[0] for r in conn.execute(
        "SELECT id FROM work_orders WHERE is_deleted=0"
        " AND COALESCE(is_bulk,0)=0" + svc
        + f" AND id IN ({','.join('?' * len(ids))})", ids)]


def bad_ids(conn, wo_ids):
    """معرّفات الفواتير الكاسرة للتناوب في سلاسل هذه الأطقم المفردة."""
    out = set()
    for wid in _singles(conn, wo_ids):
        out |= {m["id"] for m in violations(moves_of(conn, wid),
                                            birth(_wo(conn, wid)))}
    return out


def last_move(conn, wo_id):
    """آخر حركةٍ في السلسلة المنظّمة: {id, kind, date} أو None."""
    seq = order(moves_of(conn, wo_id), birth(_wo(conn, wo_id)))
    return seq[-1] if seq else None


_MOVES_SQL = (
    "SELECT DISTINCT it.work_order_id wid, i.id, i.kind, i.invoice_date date"
    " FROM invoice_items it JOIN invoices i ON i.id=it.invoice_id"
    " WHERE i.is_deleted=0 AND i.kind IN ('sale','sale_return')")


def moves_of(conn, wo_id):
    return [dict(r) for r in conn.execute(
        _MOVES_SQL + " AND it.work_order_id=?", (int(wo_id),))]


def ordered_ids(conn, wo_id):
    """معرّفات فواتير الطقم بترتيبها الحقيقي."""
    return [m["id"] for m in order(moves_of(conn, wo_id),
                                   birth(_wo(conn, wo_id)))]


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
        "SELECT w.id, w.work_order_no, w.status, w.entry_id"
        " FROM work_orders w"
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
    for wid, w in wos.items():
        mv = by.get(wid)
        # بلا حركةٍ قائمة: المُورَّد (له قيد توريد) في الخزنة — حُذفت
        # فواتيره كلها فكأنه لم يخرج. والمُدخَل ليُرتجع يبقى كما سُجّل
        want = final_state(mv, birth(w)) if mv else (
            IN_STOCK if w["entry_id"] else None)
        if want and want != w["status"]:
            conn.execute("UPDATE work_orders SET status=? WHERE id=?",
                         (want, wid))
            log_action(conn, username, "resync", "work_orders", wid,
                       f"حالة الطقم {w['work_order_no']}: "
                       f"{LABEL.get(w['status'], w['status'])} ← "
                       f"{LABEL[want]} — من تسلسل حركته")
            fixed.append((w["work_order_no"], w["status"], want))
    return fixed


def with_moves(conn, wo_ids):
    """{رقم التشغيل: [أرقام فواتيره القائمة]} — للأطقم التي لها بيعٌ أو
    مرتجع. توريدُ طقمٍ تحرّك لا يُحذف: حذفه يترك فواتيره معلّقةً على
    طقمٍ لا وجود له، فتبقى «حركته» في الكشوف والتحليلات بلا أصل."""
    ids = _singles(conn, wo_ids)
    if not ids:
        return {}
    out = {}
    for r in conn.execute(
            "SELECT w.work_order_no no, i.invoice_no inv"
            " FROM invoice_items it JOIN invoices i ON i.id=it.invoice_id"
            " JOIN work_orders w ON w.id=it.work_order_id"
            " WHERE i.is_deleted=0 AND i.kind IN ('sale','sale_return')"
            f" AND it.work_order_id IN ({','.join('?' * len(ids))})"
            " ORDER BY i.invoice_date, i.id", ids):
        out.setdefault(r["no"], []).append(r["inv"])
    return out


def assert_deletable(conn, wo_ids):
    """يرفض حذف توريدِ طقمٍ له حركة بيعٍ أو مرتجع — بأرقام فواتيره."""
    moved = with_moves(conn, wo_ids)
    if moved:
        txt = "؛ ".join(f"{no}: {'، '.join(v)}" for no, v in moved.items())
        raise ValueError(
            "لا يُحذف توريد طقمٍ له حركة بيعٍ أو مرتجع — احذف فواتيره أولاً"
            " فيعود كأنه لم يتحرّك، ثم احذف توريده:\n" + txt)
