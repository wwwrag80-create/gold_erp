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

# ══════════════════════════════════════════════════════════════════
#  الوزن (4.82): للطقم وزنه، ويُباع منه جزءٌ ويبقى الباقي في الخزنة
# ------------------------------------------------------------------
#  حالة الطقم زوج أوزان: (في الخزنة، عند الجهات). البيع ينقل وزنه من
#  الأول إلى الثاني والمرتجع يعكسه. فطقمٌ 10 جم بِيع منه العقد 5 جم
#  يبقى في الخزنة 5 جم يُباع لاحقاً، وطقمٌ خرج بوزنه كله لا يُباع.
#
#  **الحركة الكاملة**: بيعٌ لا يبقى بعده ما يُعتدّ به (فرقُ ميزانٍ لا
#  قطعة: أقل من `_slack`) يُخرج الطقم كله — وكذلك المرتجع. وحركات ما
#  قبل 4.82 كانت كلها كاملة، فتبقى سلاسلها كما كانت: بيع ← مرتجع.
#  وحركةٌ بلا وزن (بيانات قديمة) كاملةٌ دائماً.
#
#  والحالة **تُشتقّ** من السلسلة بعد كل عملية (`resync`)، فحذف فاتورة
#  أو تعديلها أو تحويلها أو نقلها يعيد حساب الوزنين من جديد.
# ══════════════════════════════════════════════════════════════════
EPS = 0.001


def _slack(x):
    """أقل باقٍ يُعتدّ به قطعةً لا فرقَ ميزان: 0.05 جم أو 2% من الوزن."""
    return max(0.05, 0.02 * abs(x))


def _over(x):
    """تجاوزٌ مقبول لوزن الباقي (فرق ميزان): 0.05 جم أو 5%."""
    return max(0.05, 0.05 * abs(x))


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


def _init(moves, start=None, full=None):
    """(في الخزنة، عند الجهات) يوم وُلد الطقم."""
    st = start or _start(_by_date(moves))
    f = float(full) if full not in (None, "") and float(full) > EPS else 1.0
    return (f, 0.0) if st == IN_STOCK else (0.0, f)


def _w(m):
    try:
        return float(m.get("w") or 0.0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _valid(state, m):
    """هل تسمح الحالة بهذه الحركة؟ بيعٌ يحتاج وزناً في الخزنة، ومرتجعٌ
    يحتاج وزناً خارجها — وجزءٌ لا يتجاوز ما بقي إلا بفرق ميزان."""
    rem, out = state
    w = _w(m)
    if m["kind"] == SALE:
        if rem <= EPS:
            return False
        return not (out > EPS and w > rem + _over(rem))
    if out <= EPS:
        return False
    return not (rem > EPS and w > out + _over(out))


def _apply(state, m):
    rem, out = state
    w = _w(m)
    if not _valid(state, m):
        # حركةٌ لا تسمح بها حالتها (بقيت بعد حذف سابقتها مثلاً): تُطبَّق
        # على ما هو موجودٌ فعلاً فلا تخلق وزناً من عدم — بيعٌ ولا شيء في
        # الخزنة لا يُخرج شيئاً، ومرتجعٌ ولا شيء خارجها لا يُدخل شيئاً
        if m["kind"] == SALE:
            return (0.0, out + max(rem, 0.0))
        return (rem + max(out, 0.0), 0.0)
    if m["kind"] == SALE:
        if w <= EPS:
            w = rem                      # حركةٌ بلا وزن: كاملة
        if rem - w <= _slack(rem):       # لا يبقى ما يُعتدّ به: كاملة
            return (0.0, out + w)
        return (rem - w, out + w)
    if w <= EPS:
        w = out
    if out - w <= _slack(out):
        return (rem + w, 0.0)
    return (rem + w, out - w)


def _state_of(st):
    return IN_STOCK if st[0] > EPS else SOLD


def order(moves, start=None, full=None):
    """الحركات بترتيبها الحقيقي: بالتاريخ، وفي اليوم الواحد ما تسمح به
    الحالة أولاً (بيعٌ ما دام في الخزنة وزن · مرتجعٌ ما دام خارجها وزن)،
    وبين الجائز يُقدَّم الأقدم إصداراً. وإن لم يجز شيء (بيانات شاذة)
    أُخذ الأقدم كما هو — فلا تضيع حركة.

    `moves`: [{"id", "kind", "date", "w"?}] بأي ترتيب."""
    moves = _by_date(moves)
    state = _init(moves, start, full)
    out = []
    for _d, day in groupby(moves, key=lambda m: m["date"] or ""):
        left = list(day)
        while left:
            pick = next((m for m in left if _valid(state, m)), left[0])
            left.remove(pick)
            out.append(pick)
            state = _apply(state, pick)
    return out


def replay(moves, start=None, full=None):
    """(في الخزنة، عند الجهات، [الحركات الكاسرة]) بعد السلسلة كلها."""
    seq = order(moves, start, full)
    state = _init(moves, start, full)
    bad = []
    for m in seq:
        if not _valid(state, m):
            bad.append(m)
        state = _apply(state, m)
    return state[0], state[1], bad


def trail(moves, start=None, full=None):
    """[(الحركة، في الخزنة بعدها، عند الجهات بعدها)] بترتيب السلسلة —
    لعرض حركة الطقم سطراً سطراً بما بقي منه بعد كلٍّ."""
    seq = order(moves, start, full)
    state = _init(moves, start, full)
    out = []
    for m in seq:
        state = _apply(state, m)
        out.append((m, round(max(state[0], 0.0), 3),
                    round(max(state[1], 0.0), 3)))
    return out


def final_state(moves, start=None, full=None):
    """حالة الطقم بعد سلسلته — `None` لطقمٍ بلا حركة (تبقى كما هي)."""
    if not moves:
        return None
    rem, _out, _bad = replay(moves, start, full)
    return IN_STOCK if rem > EPS else SOLD


def violations(moves, start=None, full=None):
    """الحركات التي لا تسمح بها حالتها في السلسلة المنظّمة — بأعيانها:
    بيعٌ ولا وزن في الخزنة، أو مرتجعٌ ولا وزن خارجها، أو جزءٌ أكبر مما
    بقي."""
    return replay(moves, start, full)[2]


_NEW = 10 ** 15            # معرّف حركةٍ لم تُحفظ بعد — آخر يومها


# علامة الطقم المُدخَل ليُرتجع (`inventory.create_return_stub`)
STUB_NOTE = "أُدخل عبر مرتجع"


def birth(wo):
    """حالة الطقم يوم وُلد: المُورَّد (له قيد توريد) في الخزنة يقيناً،
    والمُدخَل ليُرتجع خارجها يقيناً (4.85). وما سواهما (بياناتٌ قديمة)
    يُستدلّ عليه من حركته."""
    try:
        if wo["entry_id"]:
            return IN_STOCK
        if STUB_NOTE in str(wo["notes"] or ""):
            return SOLD
    except (KeyError, IndexError, TypeError):
        pass
    return None


def _born(wo, moves):
    """حالة الميلاد **من الحركات القائمة** — تُثبَّت قبل فحص حركةٍ جديدة.

    الخلل الذي تعالجه (4.85): كان الاستدلال يُعاد بعد إضافة الحركة
    المفحوصة نفسها. فطقمٌ أُدخل بمرتجع (مرتجعاته أكثر ⇒ وُلد خارجها)
    تُضاف له حركة بيع فيتساوى العددان وينقلب ميلاده «في الخزنة» —
    فيصير مرتجعه الأول كاسراً ويُرفض بيعه وباقيه في الخزنة بوزنه كله:
    «الباقي 37.200 جم فقط، والمكتوب 37.200 جم»."""
    b = birth(wo)
    if b:
        return b
    if moves:
        return _start(_by_date(moves))
    try:
        return wo["status"] or IN_STOCK
    except (KeyError, IndexError, TypeError):
        return IN_STOCK


def _full(wo):
    try:
        return float(wo["registered_weight"] or 0.0)
    except (KeyError, IndexError, TypeError):
        return None


def _wo(conn, wo_id):
    return conn.execute("SELECT * FROM work_orders WHERE id=?",
                        (int(wo_id),)).fetchone()


def state(conn, wo):
    """{"rem": في الخزنة، "out": عند الجهات، "full": وزن البطاقة} الآن."""
    full = _full(wo) or 0.0
    mv = moves_of(conn, wo["id"])
    if not mv:
        st = IN_STOCK if wo["entry_id"] else wo["status"]
        rem, out = _init([], st, full)
        return {"rem": round(rem, 3), "out": round(out, 3), "full": full}
    rem, out, _bad = replay(mv, birth(wo), full)
    return {"rem": round(max(rem, 0.0), 3), "out": round(max(out, 0.0), 3),
            "full": full}


def default_weight(conn, wo, kind):
    """الوزن الذي يُقترح للسطر: الباقي في الخزنة للبيع، والخارج للمرتجع —
    وزن البطاقة إن لم يكن شيء (الرقم التجميعي وزنه ما يُكتب)."""
    try:
        if wo["is_bulk"]:
            return float(wo["registered_weight"] or 0.0)
    except (KeyError, IndexError):
        pass
    s = state(conn, wo)
    v = s["rem"] if kind == SALE else s["out"]
    return v if v > EPS else s["full"]


def can_add(conn, wo, kind, date, weight=None):
    """هل تستقيم السلسلة إن أُضيفت هذه الحركة بهذا التاريخ وهذا الوزن؟"""
    return refusal(conn, wo, kind, date, weight) is None


def _pos(seq, init, mid):
    """(في الخزنة، عند الجهات) قبل الحركة `mid` في السلسلة المنظّمة."""
    state = init
    for m in seq:
        if m["id"] == mid:
            return state
        state = _apply(state, m)
    return state


def refusal(conn, wo, kind, date, weight=None):
    """`None` إن استقامت السلسلة بالحركة الجديدة، وإلا سبب الرفض نصاً.

    بلا حركاتٍ سابقة: الطقم يُحكم بحالة ميلاده. ومع حركات: تُدرج الجديدة
    في يومها ويُنظر أتكسر السلسلة أم لا — فالبيع بتاريخٍ قديم قبل مرتجعٍ
    لاحق يُرفض كما يُرفض بيع ما خرج بوزنه كله، وبيعُ جزءٍ أكبر مما بقي.

    والسبب يُسمّى بعينه (4.85): وزنٌ أكبر من الباقي، أو تاريخٌ يسبق حركةً
    قائمة (فيُدلّ على التاريخ الذي يصحّ منه) — لا «الباقي X والمكتوب X».
    والطقم الذي لا شيء منه في الخزنة (أو خارجها للمرتجع) يُترك سببه
    للمتصل (`invoices._where_is`)، فتُعاد كلمة "none-left".
    """
    import datetime as _dt
    full = _full(wo)
    w = float(weight or 0.0)
    new = {"id": _NEW, "kind": kind,
           "date": str(date or _dt.date.today().isoformat())[:10], "w": w}
    mv = moves_of(conn, wo["id"])
    b = _born(wo, mv)
    init = _init(mv, b, full)
    if not mv:
        if _valid(init, new):
            return None
        return _weight_why(wo, kind, init, w)
    before = {m["id"] for m in violations(mv, b, full)}
    after = {m["id"] for m in violations(mv + [new], b, full)}
    if _NEW not in after and after <= before:
        return None
    rem, out, _bad = replay(mv, b, full)
    now = rem if kind == SALE else out
    if now <= EPS:
        return "none-left"
    last = max(m["date"] or "" for m in mv)
    seq = order(mv + [new], b, full)
    at = _pos(seq, init, _NEW)
    at_part = at[0] if kind == SALE else at[1]
    if _NEW in after and at_part > EPS:
        # في تاريخه كان منه شيءٌ — فالمانع الوزن
        return _weight_why(wo, kind, at, w)
    if new["date"] < last:
        later = sorted((m for m in mv if (m["date"] or "") > new["date"]),
                       key=lambda m: (m["date"] or "", m["id"]))
        m0 = later[0]
        no = _inv_no(conn, m0["id"])
        lbl = "بيع" if m0["kind"] == SALE else "مرتجع"
        return (f"الطقم {wo['work_order_no']}: تاريخ الفاتورة {new['date']}"
                f" يسبق حركةً له — {lbl} بالفاتورة {no} بتاريخ"
                f" {m0['date']}.\nاجعل تاريخ الفاتورة {last} أو بعده.")
    # سلسلةٌ مكسورةٌ أصلاً في يومها (حركتان متعارضتان قائمتان): ترتيب
    # الجديدة بينها لا يُقطع به، وقبولها قد يُبقي الطقم «في الخزنة» بعد
    # بيعه — فيُدلّ على الحركات المعارضة لتُصحَّح أولاً
    broken = sorted(i for i in (before | after) if i != _NEW)
    if broken:
        nos = "، ".join(str(_inv_no(conn, i)) for i in broken)
        return (f"الطقم {wo['work_order_no']}: حركته غير منتظمة أصلاً"
                f" (الفواتير {nos}) — راجعها في «حركة الطقم» وصحّحها"
                " أولاً، ثم أعد المحاولة.")
    return _weight_why(wo, kind, (rem, out), w)


def _weight_why(wo, kind, state, w):
    rem, out = state
    part = rem if kind == SALE else out
    if part <= EPS:
        return "none-left"
    return (f"الطقم {wo['work_order_no']}: "
            + ("الباقي منه في الخزنة" if kind == SALE
               else "الخارج منه عند الجهات")
            + f" {part:,.3f} جم فقط، والمكتوب {w:,.3f} جم")


def _inv_no(conn, invoice_id):
    r = conn.execute("SELECT invoice_no FROM invoices WHERE id=?",
                     (int(invoice_id),)).fetchone()
    return r[0] if r else invoice_id


def _singles(conn, wo_ids):
    """الأطقم المفردة من بين هذه — لا التجميعي ولا الطقم الخدمي «أجر»
    (كلاهما يُباع مراراً بطبيعته فلا سلسلة له)."""
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
    """معرّفات الفواتير الكاسرة لسلاسل هذه الأطقم المفردة."""
    out = set()
    for wid in _singles(conn, wo_ids):
        wo = _wo(conn, wid)
        out |= {m["id"] for m in violations(moves_of(conn, wid),
                                            birth(wo), _full(wo))}
    return out


def last_move(conn, wo_id):
    """آخر حركةٍ في السلسلة المنظّمة: {id, kind, date, w} أو None."""
    wo = _wo(conn, wo_id)
    seq = order(moves_of(conn, wo_id), birth(wo), _full(wo))
    return seq[-1] if seq else None


def last_out(conn, wo, as_of=None):
    """آخر بيعٍ أخرج الطقم حتى `as_of` — للمرتجع: «كم جلس عند الجهة» (4.87).

    بترتيب السلسلة المنظّمة: البيع الذي بعده لا يزال منه شيءٌ خارجاً.
    يعيد {"invoice_no", "date", "party", "party_id", "days", "out"} أو
    None (لا بيع، أو لا شيء منه خارجٌ في ذلك التاريخ)."""
    import datetime as _dt
    mv = moves_of(conn, wo["id"])
    if not mv:
        return None
    d = str(as_of or _dt.date.today().isoformat())[:10]
    sale, out = None, 0.0
    for m, _rem, o in trail(mv, birth(wo), _full(wo)):
        if (m["date"] or "") > d:
            break
        if m["kind"] == SALE:
            sale = m
        out = o
    if sale is None or out <= EPS:
        return None
    r = conn.execute(
        "SELECT i.invoice_no, i.customer_id, e.name FROM invoices i"
        " LEFT JOIN entities e ON e.id=i.customer_id WHERE i.id=?",
        (sale["id"],)).fetchone()
    try:
        days = (_dt.date.fromisoformat(d)
                - _dt.date.fromisoformat(str(sale["date"])[:10])).days
    except ValueError:
        return None
    return {"invoice_no": r[0] if r else "", "date": sale["date"],
            "party": (r[2] if r else "") or "—",
            "party_id": r[1] if r else None, "days": days, "out": out}


def days_ar(n):
    """المدة بالعربية: «يومٌ واحد» · «يومان» · «5 أيام» · «23 يوماً» —
    ومن الشهر فأكثر تُضاف الأشهر: «47 يوماً (شهر و17 يوماً)»."""
    n = int(n)

    def one(k, w1, w2, w3, w11):
        if k == 1:
            return w1
        if k == 2:
            return w2
        return f"{k} {w3 if 3 <= k % 100 <= 10 else w11}"
    txt = one(n, "يومٌ واحد", "يومان", "أيام", "يوماً")
    if n < 30:
        return txt
    mo, dd = divmod(n, 30)
    m_txt = one(mo, "شهر", "شهران", "أشهر", "شهراً")
    if dd:
        m_txt += " و" + one(dd, "يوم", "يومان", "أيام", "يوماً")
    return f"{txt} ({m_txt} تقريباً)"


# حركة كل فاتورة على الطقم بوزنها (مجموع أسطره فيها)
_MOVES_SQL = (
    "SELECT it.work_order_id wid, i.id, i.kind, i.invoice_date date,"
    " SUM(it.registered_weight) w"
    " FROM invoice_items it JOIN invoices i ON i.id=it.invoice_id"
    " WHERE i.is_deleted=0 AND i.kind IN ('sale','sale_return')")
_MOVES_GROUP = " GROUP BY it.work_order_id, i.id"


def moves_of(conn, wo_id):
    return [dict(r) for r in conn.execute(
        _MOVES_SQL + " AND it.work_order_id=?" + _MOVES_GROUP,
        (int(wo_id),))]


def ordered_ids(conn, wo_id):
    """معرّفات فواتير الطقم بترتيبها الحقيقي."""
    wo = _wo(conn, wo_id)
    return [m["id"] for m in order(moves_of(conn, wo_id), birth(wo),
                                   _full(wo))]


def is_last(conn, wo_id, invoice_id):
    """هل الفاتورة آخر حركةٍ للطقم في سلسلته المنظّمة؟"""
    ids = ordered_ids(conn, wo_id)
    return not ids or ids[-1] == int(invoice_id)


def resync(conn, wo_ids=None, username="system"):
    """يضبط حالة كل طقمٍ مفرد ووزنه الباقي على نتيجة سلسلته — ويسجّل ما
    صُحِّح.

    `wo_ids=None` ← كل الأطقم (فحص الإقلاع). يُعيد [(رقم التشغيل، من، إلى)].
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(work_orders)")}
    where = "COALESCE(w.is_bulk,0)=0"
    if "is_service" in cols:
        where += " AND COALESCE(w.is_service,0)=0"
    has_rem = "remaining_weight" in cols
    params = []
    if wo_ids is not None:
        ids = sorted({int(i) for i in wo_ids if i})
        if not ids:
            return []
        where += f" AND w.id IN ({','.join('?' * len(ids))})"
        params = ids
    wos = {r["id"]: r for r in conn.execute(
        "SELECT w.* FROM work_orders w"
        f" WHERE w.is_deleted=0 AND {where}", params)}
    if not wos:
        return []
    sql, args = _MOVES_SQL, []
    if wo_ids is not None:
        sql += f" AND it.work_order_id IN ({','.join('?' * len(wos))})"
        args = list(wos)
    by = {}
    for r in conn.execute(sql + _MOVES_GROUP, args):
        if r["wid"] in wos:
            by.setdefault(r["wid"], []).append(dict(r))
    fixed = []
    for wid, w in wos.items():
        mv = by.get(wid)
        full = _full(w) or 0.0
        if mv:
            rem, _out, _bad = replay(mv, birth(w), full)
            want = IN_STOCK if rem > EPS else SOLD
            rem = round(max(rem, 0.0), 3)
        else:
            # بلا حركةٍ قائمة: المُورَّد (له قيد توريد) في الخزنة بوزنه
            # كله — حُذفت فواتيره كلها فكأنه لم يخرج. والمُدخَل ليُرتجع
            # يبقى كما سُجّل
            want = IN_STOCK if w["entry_id"] else None
            rem = full if (want or w["status"]) == IN_STOCK else 0.0
        # الوزن الباقي يُكتب لطقمٍ في الخزنة بوزنٍ غير وزن بطاقته (بِيع
        # منه جزء، أو عاد بوزنٍ آخر) — وإلا NULL: وزن البطاقة نفسه
        st_now = want or w["status"]
        keep = (rem if st_now == IN_STOCK and abs(rem - full) > EPS
                else None)
        if has_rem:
            cur = w["remaining_weight"]
            if (cur is None) != (keep is None) or (
                    keep is not None and abs(float(cur) - keep) > EPS):
                conn.execute("UPDATE work_orders SET remaining_weight=?"
                             " WHERE id=?", (keep, wid))
        if want and want != w["status"]:
            conn.execute("UPDATE work_orders SET status=? WHERE id=?",
                         (want, wid))
            log_action(conn, username, "resync", "work_orders", wid,
                       f"حالة الطقم {w['work_order_no']}: "
                       f"{LABEL.get(w['status'], w['status'])} ← "
                       f"{LABEL[want]} — من تسلسل حركته")
            fixed.append((w["work_order_no"], w["status"], want))
    return fixed


def irregular(conn, limit=200):
    """[(طقم، [الفواتير الكاسرة])] لكل طقمٍ مفرد سلسلته غير منتظمة —
    بيعٌ ولا شيء منه في الخزنة، أو مرتجعٌ ولا شيء منه خارجها، أو جزءٌ
    أكبر مما بقي. بالوزن (4.85): بيعُ جزءين من طقمٍ واحد ليس تكراراً."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(work_orders)")}
    svc = (" AND COALESCE(w.is_service,0)=0" if "is_service" in cols
           else "")
    wos = {r["id"]: r for r in conn.execute(
        "SELECT w.* FROM work_orders w WHERE w.is_deleted=0"
        " AND COALESCE(w.is_bulk,0)=0" + svc)}
    by = {}
    for r in conn.execute(_MOVES_SQL + _MOVES_GROUP):
        if r["wid"] in wos:
            by.setdefault(r["wid"], []).append(dict(r))
    out = []
    for wid, mv in by.items():
        w = wos[wid]
        bad = violations(mv, birth(w), _full(w))
        if bad:
            out.append((w, [m["id"] for m in bad]))
            if len(out) >= limit:
                break
    return out


def with_moves(conn, wo_ids):
    """{رقم التشغيل: [أرقام فواتيره القائمة]} — للأطقم التي لها بيعٌ أو
    مرتجع. توريدُ طقمٍ تحرّك لا يُحذف: حذفه يترك فواتيره معلّقةً على
    طقمٍ لا وجود له، فتبقى «حركته» في الكشوف والتحليلات بلا أصل."""
    ids = _singles(conn, wo_ids)
    if not ids:
        return {}
    out = {}
    for r in conn.execute(
            "SELECT DISTINCT w.work_order_no no, i.invoice_no inv,"
            " i.invoice_date d, i.id iid"
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
