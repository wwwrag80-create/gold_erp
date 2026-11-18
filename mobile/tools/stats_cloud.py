"""إعداد إحصاءات الاستخدام على Cloudflare وفحصها — من GitHub Actions («إحصاءات الاستخدام»):

    CLOUDFLARE_API_TOKEN=… python3 mobile/tools/stats_cloud.py [setup|check]

setup (يتكرر بلا ضرر):
  - قاعدتان D1 مجانيتان: aur-stats (الموقع) وaur-stats-test (موقع التجربة) — تُنشآن إن لم توجدا.
    مستقلتان تماماً عن سحابة Supabase ومساحتها.
  - تُربطان بمشروع Pages «gold-erp» باسم STATS (الإنتاج ← aur-stats، والتجربة ← aur-stats-test)،
    دون مسّ أي إعدادٍ آخر في المشروع (يُتحقّق من ذلك بعد الربط).
  - إن تغيّر الربط: تُعاد آخر نسخةٍ تجريبية للفرع فيعمل فيها، والإنتاج يعمل من أول نشرٍ قادم.
check:
  - رسالةٌ تجريبية إلى موقع التجربة ثم قراءتها من قاعدته (الاستقبال يعمل فعلاً)، ثم حذف رسائل الاختبار.
  - ويُطبع عن القاعدتين ما يكفي للتأكد فقط — لا أرقام المستخدمين (سجلّ GitHub هنا عام).

المفتاح (CLOUDFLARE_API_TOKEN) يُضاف مرةً في أسرار المستودع بصلاحيتين: D1 (Edit) وCloudflare Pages (Edit).
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("CF_API_BASE", "https://api.cloudflare.com/client/v4")   # البديل للاختبار فقط
PROJECT = "gold-erp"
BRANCH = "claude/gold-accounting-system-9o1vmw"
TRIAL_SITE = os.environ.get("STATS_TRIAL_SITE", "https://claude-gold-accounting-syste.gold-erp.pages.dev")
DBS = {"production": "aur-stats", "preview": "aur-stats-test"}
BINDING = "STATS"
ACCOUNT_FALLBACK = "aefc044963986818fb392d947e9fc19c"   # من روابط لوحة Cloudflare في فحوص المستودع (ليس سرّاً)
TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()


class CFError(Exception):
    pass


def cf(method, path, body=None, raw_url=None):
    req = urllib.request.Request(raw_url or API + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json",
                                          "User-Agent": "aur-stats-setup"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read() or b"{}")
        except ValueError:
            data = {}
        msg = "; ".join(f"{x.get('code')}: {x.get('message')}" for x in data.get("errors", [])) or str(e)
        raise CFError(f"{method} {path} → {e.code} {msg}") from None
    if not data.get("success", True):
        raise CFError(f"{method} {path} → {data.get('errors')}")
    return data.get("result")


def mask(acc):
    return acc[:4] + "…" + acc[-3:]


def account():
    ids = []
    try:
        ids = [a["id"] for a in (cf("GET", "/accounts?per_page=50") or [])]
        print(f"  الحسابات التي يراها المفتاح: {len(ids)}", [mask(a) for a in ids])
    except CFError as e:
        print("  (قائمة الحسابات غير متاحة بهذا المفتاح:", e, ")")
    seen = []
    for acc in dict.fromkeys(ids + [ACCOUNT_FALLBACK]):
        try:
            cf("GET", f"/accounts/{acc}/pages/projects/{PROJECT}")
            return acc
        except CFError as e:
            seen.append(acc)
            print(f"  مشروع {PROJECT} في الحساب {mask(acc)}: {e}")
            try:
                names = [x.get("name") for x in (cf("GET", f"/accounts/{acc}/pages/projects") or [])]
                print(f"  مشاريع Pages التي يراها المفتاح في {mask(acc)}:", names)
            except CFError as e2:
                print(f"  قائمة مشاريع Pages في {mask(acc)}: {e2}")
            try:
                cf("GET", f"/accounts/{acc}/d1/database?per_page=5")
                print(f"  صلاحية D1 في {mask(acc)}: ✔")
            except CFError as e3:
                print(f"  صلاحية D1 في {mask(acc)}: {e3}")
    for path in ("/user/tokens/verify", f"/accounts/{ACCOUNT_FALLBACK}/tokens/verify"):
        try:
            r = cf("GET", path) or {}
            print(f"  فحص المفتاح ({path.split('/')[1]}): {r.get('status')}")
        except CFError as e:
            print(f"  فحص المفتاح ({path.split('/')[1]}): {e}")
    raise CFError("لم يُعثر على مشروع Pages «gold-erp» بهذا المفتاح — تأكّد من صلاحية Cloudflare Pages (Edit)")


def database(acc, name, create=True):
    found = [d for d in (cf("GET", f"/accounts/{acc}/d1/database?name={name}&per_page=50") or []) if d.get("name") == name]
    if found:
        return found[0]["uuid"], False
    if not create:
        return None, False
    return cf("POST", f"/accounts/{acc}/d1/database", {"name": name})["uuid"], True


def query(acc, uuid, sql, params=None):
    res = cf("POST", f"/accounts/{acc}/d1/database/{uuid}/query", {"sql": sql, "params": params or []})
    return (res or [{}])[0].get("results", [])


def shape(cfg):
    """ما في إعداد البيئة من أسماء (بلا قيم) — للتأكد أن الربط لم يمسّ غيره."""
    out = {}
    for k, v in (cfg or {}).items():
        out[k] = sorted(v.keys()) if isinstance(v, dict) else v
    return out


def setup():
    acc = account()
    print("✔ الحساب والمشروع:", PROJECT)
    ids = {}
    for env, name in DBS.items():
        ids[env], made = database(acc, name)
        print(f"✔ قاعدة {name}:", "أُنشئت الآن" if made else "موجودة")
    proj = cf("GET", f"/accounts/{acc}/pages/projects/{PROJECT}")
    dc = proj.get("deployment_configs") or {}
    before = {env: shape(dc.get(env)) for env in DBS}
    patch = {}
    for env in DBS:
        cur = ((dc.get(env) or {}).get("d1_databases") or {}).get(BINDING) or {}
        if cur.get("id") != ids[env]:
            patch[env] = {"d1_databases": {BINDING: {"id": ids[env]}}}
    if not patch:
        print("✔ الربط موجود (STATS) في الإنتاج والتجربة")
        return acc, ids, False
    cf("PATCH", f"/accounts/{acc}/pages/projects/{PROJECT}", {"deployment_configs": patch})
    dc2 = (cf("GET", f"/accounts/{acc}/pages/projects/{PROJECT}").get("deployment_configs") or {})
    for env in DBS:
        got = ((dc2.get(env) or {}).get("d1_databases") or {}).get(BINDING) or {}
        if got.get("id") != ids[env]:
            raise CFError(f"الربط لم يُحفظ في {env}")
        after = shape(dc2.get(env))
        lost = [k for k, v in before[env].items() if k != "d1_databases" and after.get(k) != v]
        if lost:
            raise CFError(f"تغيّر في {env} غير الربط: {lost} — أوقفتُ هنا للمراجعة")
    print("✔ رُبطت القاعدتان بالموقع (STATS) — ولم يتغيّر غير ذلك:",
          {env: [k for k in before[env] if k != "d1_databases"] for env in DBS})
    # نسخة التجربة للفرع: إعادة آخر نشرٍ ليعمل فيه الربط
    deps = cf("GET", f"/accounts/{acc}/pages/projects/{PROJECT}/deployments?env=preview&per_page=25") or []
    mine = [d for d in deps if ((d.get("deployment_trigger") or {}).get("metadata") or {}).get("branch") == BRANCH]
    if mine:
        try:
            wait_deploy(acc, mine[0]["id"])     # نشرٌ جارٍ من الدفعة نفسها: ننتظره أولاً
        except CFError as e:
            print("  (آخر نشرٍ للفرع:", e, ")")
        new = cf("POST", f"/accounts/{acc}/pages/projects/{PROJECT}/deployments/{mine[0]['id']}/retry")
        print("✔ أُعيد نشر موقع التجربة ليعمل فيه الربط")
        wait_deploy(acc, new["id"])
    return acc, ids, True


def wait_deploy(acc, dep_id, limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        d = cf("GET", f"/accounts/{acc}/pages/projects/{PROJECT}/deployments/{dep_id}")
        st = (d.get("latest_stage") or {})
        if st.get("name") == "deploy" and st.get("status") == "success":
            print(f"✔ النشر اكتمل ({int(time.time() - t0)} ث)")
            return True
        if st.get("status") == "failure":
            raise CFError(f"فشل النشر في مرحلة {st.get('name')}")
        time.sleep(10)
    raise CFError("النشر لم يكتمل في الوقت")


def http(method, url, body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=body, headers={"User-Agent": "aur-stats-check", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def check(acc=None, ids=None):
    acc = acc or account()
    ids = ids or {env: database(acc, name, create=False)[0] for env, name in DBS.items()}
    if not all(ids.values()):
        raise CFError("القاعدتان غير موجودتين بعد — شغّل setup")
    test_id = f"test-ci-{int(time.time())}-{os.getpid()}"
    ok = False
    for attempt in range(12):           # موقع التجربة قد يحتاج دقيقةً بعد النشر
        code, _ = http("POST", TRIAL_SITE + "/api/p",
                       json.dumps({"i": test_id, "v": "1.15.0", "p": "trial", "o": 1}).encode(),
                       {"Content-Type": "text/plain", "Origin": "https://appassets.androidplatform.net"})
        if code == 200:
            ok = True
            break
        print(f"  … موقع التجربة يردّ {code} — انتظار")
        time.sleep(15)
    if not ok:
        raise CFError("موقع التجربة لا يستقبل الرسائل بعد")
    rows = query(acc, ids["preview"], "SELECT id, ver, plat, first_day FROM devices WHERE id=?", [test_id])
    if not rows:
        raise CFError("وصلت الرسالة لكنها لم تُحفظ في القاعدة")
    print("✔ رسالةٌ تجريبية وصلت وحُفظت في قاعدة التجربة:", rows[0]["plat"], rows[0]["ver"], rows[0]["first_day"])
    trial = query(acc, ids["preview"],
                  "SELECT COUNT(*) n, MAX(last_ts) t FROM devices WHERE plat='trial' AND id NOT LIKE 'test-%'")
    n = (trial[0] if trial else {}).get("n") or 0
    last = (trial[0] if trial else {}).get("t")
    print(f"✔ أجهزة النسخة التجريبية في قاعدة التجربة: {n}"
          + (f" · آخر رسالة {time.strftime('%Y-%m-%d %H:%M', time.gmtime(last / 1000 + 3 * 3600))} (الرياض)" if last else ""))
    for sql in ("DELETE FROM devices WHERE id LIKE 'test-%'", "DELETE FROM act WHERE id LIKE 'test-%'",
                "DELETE FROM updates WHERE id LIKE 'test-%'"):
        query(acc, ids["preview"], sql)
    print("✔ حُذفت رسائل الاختبار")
    try:
        prod = query(acc, ids["production"], "SELECT COUNT(*) > 0 has FROM devices")
        print("✔ قاعدة الموقع جاهزة —", "فيها بيانات" if prod and prod[0].get("has") else "تنتظر أول رسالة")
    except CFError as e:
        if "no such table" not in str(e):
            raise
        print("✔ قاعدة الموقع جاهزة — تنتظر أول رسالة (تُنشأ جداولها تلقائياً)")


def main():
    if not TOKEN:
        print("ℹ لم يُضف مفتاح Cloudflare بعد (سرّ المستودع CLOUDFLARE_API_TOKEN) — لا شيء يُفعل الآن.")
        return 0
    action = (sys.argv[1] if len(sys.argv) > 1 else "setup").strip().lower()
    try:
        if action == "setup":
            acc, ids, _changed = setup()
            check(acc, ids)
        elif action == "check":
            check()
        else:
            print("الاستخدام: stats_cloud.py [setup|check]")
            return 2
    except CFError as e:
        print("✘", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
