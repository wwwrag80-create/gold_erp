# -*- coding: utf-8 -*-
"""مجموعات العملاء والجهات (4.79) — «عملاء الرميزان» وأمثالها.

**الفكرة المحاسبية**: المجموعة حسابٌ تجميعي (رئيسي) تحت «إجمالي العملاء»
1600 — أو «إجمالي الجهات الأخرى» 1650 — وحساباتُ عملائها فروعٌ تحته:

    1600  إجمالي العملاء
      1601  عملاء الرميزان            ← مجموعة (لا تقبل قيداً مباشراً)
        160101  عميل: محمد            ← رصيده الخاص وكشفه
        160102  عميل: سالم
      1602  عميل: أحمد                ← عميلٌ بلا مجموعة

فرصيد المجموعة مجموعُ أرصدة عملائها، ولكل عميلٍ رصيده وكشفه، ويبقى
العميل عميلاً في كل الشاشات (نوعه من مجموعته الرقابية 1600 مهما تعمّق).
ونقلُ العميل بين المجموعات نقلٌ لحسابه في الشجرة لا قيدٌ — فلا يتغيّر
رقمٌ في أي كشف أو قائمة.

وتُحفظ معرّفات المجموعات في الإعدادات، فتبقى مجموعةً وإن خلت من عملائها
(الدليل يُعيد الحساب الفارغ حسابَ حركة)؛ وكل حسابٍ تجميعي يضيفه المحاسب
تحت 1600 أو 1650 من دليل الحسابات مجموعةٌ هنا أيضاً.
"""
import json

from models import coa
from services.audit import log_action

ROOTS = {"customer": "1600", "other": "1650"}
KIND_LABELS = {"customer": "العملاء", "other": "الجهات الأخرى"}
_KEY = "party_groups"


# ══════════════════════════════════════════════════════════════════
#  التخزين
# ══════════════════════════════════════════════════════════════════

def _ids(conn):
    from models import fiscal
    try:
        raw = fiscal.get_setting(conn, _KEY, "")
        return {int(x) for x in (json.loads(raw) if raw else [])}
    except Exception:
        return set()


def _save_ids(conn, ids, username=None):
    from models import fiscal
    fiscal.set_setting(conn, _KEY, json.dumps(sorted(int(i) for i in ids)),
                       username)


def root_id(conn, kind="customer"):
    r = conn.execute("SELECT id FROM accounts WHERE code=?",
                     (ROOTS[kind],)).fetchone()
    if not r:
        raise ValueError(f"الحساب الرئيسي {ROOTS[kind]} غير موجود في الدليل")
    return r["id"]


def _tree(conn, root):
    """{معرّف: صف الحساب} لشجرة الأصل كلها (بما فيها الأصل)."""
    rows = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, code, name, parent_id, is_postable, is_active"
        " FROM accounts")}
    kids = {}
    for a, r in rows.items():
        kids.setdefault(r["parent_id"], []).append(a)
    out, todo = {}, [root]
    while todo:
        a = todo.pop()
        if a in out or a not in rows:
            continue
        out[a] = rows[a]
        todo += kids.get(a, [])
    return out


def _kids_map(tree):
    kids = {}
    for a, r in tree.items():
        kids.setdefault(r["parent_id"], []).append(a)
    return kids


def _is_group(conn, acc, root, stored, kids):
    return (acc["id"] != root
            and (acc["id"] in stored or not acc["is_postable"]
                 or acc["id"] in kids))


def _balances(conn, ids, date_to=None):
    """{حساب: (ذهب، نقد)} بقراءةٍ واحدة — مدينٌ موجب."""
    ids = list(ids)
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    cond, args = "", list(ids)
    if date_to:
        cond, args = " AND e.entry_date<=?", args + [date_to]
    return {r["a"]: (round(r["g"] or 0.0, 3), round(r["c"] or 0.0, 2))
            for r in conn.execute(
                "SELECT l.account_id a, SUM(l.gold_debit-l.gold_credit) g,"
                " SUM(l.cash_debit-l.cash_credit) c FROM journal_lines l"
                " JOIN journal_entries e ON e.id=l.entry_id"
                f" WHERE e.is_deleted=0 AND l.account_id IN ({q}){cond}"
                " GROUP BY l.account_id", args)}


def _subtree(tree, kids, a):
    out, todo = [], [a]
    while todo:
        x = todo.pop()
        out.append(x)
        todo += kids.get(x, [])
    return out


# ══════════════════════════════════════════════════════════════════
#  القراءة
# ══════════════════════════════════════════════════════════════════

def groups(conn, kind="customer", date_to=None):
    """المجموعات بترتيب الدليل: الاسم والكود وعدد الجهات والرصيدان."""
    root = root_id(conn, kind)
    tree = _tree(conn, root)
    kids = _kids_map(tree)
    stored = _ids(conn)
    ents = {r["account_id"] for r in conn.execute(
        "SELECT account_id FROM entities WHERE is_deleted=0"
        " AND account_id IS NOT NULL")}
    bal = _balances(conn, tree, date_to)
    out = []
    for a, r in tree.items():
        if not _is_group(conn, r, root, stored, kids) or a in ents:
            continue
        sub = _subtree(tree, kids, a)
        members = [x for x in sub if x in ents]
        g = sum(bal.get(x, (0, 0))[0] for x in sub)
        c = sum(bal.get(x, (0, 0))[1] for x in sub)
        depth, p = 0, r["parent_id"]
        while p and p != root and depth < 20:
            depth += 1
            p = tree.get(p, {}).get("parent_id")
        out.append({"id": a, "code": r["code"], "name": r["name"],
                    "parent_id": r["parent_id"], "depth": depth,
                    "count": len(members), "gold": round(g, 3),
                    "cash": round(c, 2)})
    out.sort(key=lambda x: x["code"])
    return out


def members(conn, group_id, date_to=None, kind="customer"):
    """جهات المجموعة (ومجموعاتها الفرعية) برصيد كلٍّ منها.

    `group_id=None`: من لا مجموعة لهم — حساباتهم تحت الأصل مباشرة."""
    root = root_id(conn, kind)
    tree = _tree(conn, root)
    kids = _kids_map(tree)
    if group_id is None:
        under = [a for a in kids.get(root, [])]
    else:
        if int(group_id) not in tree:
            raise ValueError("المجموعة غير موجودة في هذا القسم")
        under = _subtree(tree, kids, int(group_id))
    under = set(under)
    rows = conn.execute(
        "SELECT id, name, phone, entity_type, account_id FROM entities"
        " WHERE is_deleted=0 AND account_id IS NOT NULL").fetchall()
    rows = [r for r in rows if r["account_id"] in under]
    bal = _balances(conn, [r["account_id"] for r in rows], date_to)
    out = []
    for r in rows:
        acc = tree[r["account_id"]]
        par = tree.get(acc["parent_id"])
        g, c = bal.get(r["account_id"], (0.0, 0.0))
        out.append({"entity_id": r["id"], "name": r["name"],
                    "phone": r["phone"] or "", "account_id": r["account_id"],
                    "code": acc["code"],
                    "sub": (par["name"] if par and acc["parent_id"]
                            not in (root, group_id) else ""),
                    "gold": g, "cash": c})
    out.sort(key=lambda x: x["code"])
    return out


def group_of(conn, entity_id):
    """أقرب مجموعةٍ لحساب الجهة — أو None إن كانت تحت الأصل مباشرة."""
    e = conn.execute("SELECT account_id, entity_type FROM entities"
                     " WHERE id=?", (entity_id,)).fetchone()
    if not e or e["entity_type"] not in ROOTS:
        return None
    root = root_id(conn, e["entity_type"])
    acc = coa.get_account(conn, e["account_id"])
    p = acc["parent_id"] if acc else None
    if not p or p == root:
        return None
    g = coa.get_account(conn, p)
    return {"id": g["id"], "code": g["code"], "name": g["name"]}


# ══════════════════════════════════════════════════════════════════
#  الكتابة
# ══════════════════════════════════════════════════════════════════

def _check_group(conn, group_id, kind):
    root = root_id(conn, kind)
    tree = _tree(conn, root)
    gid = int(group_id)
    if gid == root or gid not in tree:
        raise ValueError(f"اختر مجموعةً من مجموعات {KIND_LABELS[kind]}")
    if conn.execute("SELECT 1 FROM entities WHERE account_id=?"
                    " AND is_deleted=0", (gid,)).fetchone():
        raise ValueError("هذا حساب جهة لا مجموعة")
    return gid


def create_group(conn, name, username, kind="customer", parent_id=None):
    """مجموعةٌ جديدة: حسابٌ تجميعي تحت الأصل (أو تحت مجموعةٍ أخرى)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("أدخل اسم المجموعة — مثل «عملاء الرميزان»")
    par = (_check_group(conn, parent_id, kind) if parent_id
           else root_id(conn, kind))
    res = coa.add_sub_account(conn, par, name, username)
    # المجموعة لا تقبل قيداً مباشراً: رصيدها مجموع فروعها
    conn.execute("UPDATE accounts SET is_postable=0 WHERE id=?",
                 (res["id"],))
    ids = _ids(conn)
    ids.add(res["id"])
    _save_ids(conn, ids, username)
    log_action(conn, username, "create", "party_groups", res["id"],
               f"مجموعة {KIND_LABELS[kind]}: {res['code']} — {name}")
    return res["id"]


def rename_group(conn, group_id, name, username, kind="customer"):
    gid = _check_group(conn, group_id, kind)
    return coa.rename_account(conn, gid, name, username)


def delete_group(conn, group_id, username, kind="customer"):
    """تُحذف المجموعة الخالية وحدها — من فيها يُنقل أولاً."""
    gid = _check_group(conn, group_id, kind)
    if coa.child_count(conn, gid):
        raise ValueError("المجموعة فيها جهات — انقلها إلى مجموعةٍ أخرى أو"
                         " أخرجها منها أولاً")
    coa.delete_account(conn, gid, username)
    ids = _ids(conn)
    ids.discard(gid)
    _save_ids(conn, ids, username)
    return True


def _keep_groups(conn, kind):
    """مجموعةٌ خلت من فروعها تبقى مجموعة (الدليل يعيدها حسابَ حركة)."""
    stored = _ids(conn)
    tree = _tree(conn, root_id(conn, kind))
    for gid in stored & set(tree):
        if not coa.has_movement(conn, gid, live_only=False):
            conn.execute("UPDATE accounts SET is_postable=0 WHERE id=?",
                         (gid,))


def assign(conn, entity_ids, group_id, username, kind="customer"):
    """ينقل حسابات الجهات تحت المجموعة (أو إلى الأصل إن كانت None).

    نقلٌ في الشجرة لا قيد: الأرصدة والكشوف كما هي. يعيد عدد من نُقل."""
    target = (_check_group(conn, group_id, kind) if group_id
              else root_id(conn, kind))
    n = 0
    for eid in entity_ids:
        e = conn.execute("SELECT * FROM entities WHERE id=? AND is_deleted=0",
                         (int(eid),)).fetchone()
        if not e:
            continue
        if e["entity_type"] != kind:
            raise ValueError(f"«{e['name']}» ليس من {KIND_LABELS[kind]}")
        acc = coa.get_account(conn, e["account_id"])
        if not acc or acc["parent_id"] == target:
            continue
        coa.move_account(conn, e["account_id"], target, username,
                         entity_ok=True)
        n += 1
    _keep_groups(conn, kind)
    if n:
        g = coa.get_account(conn, target)
        log_action(conn, username, "update", "party_groups", target,
                   f"نقل {n} إلى «{g['name']}»")
    return n
