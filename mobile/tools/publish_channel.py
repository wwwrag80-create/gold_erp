"""نشر تحديث الجوال للمستخدمين — من GitHub، لا من داخل التطبيق.

يعلن في قناة التحديث (الصفحة #23 في المستودع) إصداراً من `mobile/dist` بعد
التحقّق من ملفه: بصمته كما في `versions.json`، واسم الحزمة ورقم الإصدار من
الملف نفسه (aapt2)، وأنه موقّعٌ بمفتاح المالك (apksigner). فتقرأ التطبيقات
القناة، وتُنزّل الملف من المستودع، وتُنبّه أصحابها لتثبيته.

يُشغّله سير العمل «نشر تحديث الجوال» (`.github/workflows/mobile-publish.yml`):
    VERSION   الإصدار (فارغ = الأحدث في versions.json)
    NOTES     ما الجديد (فارغ = ملاحظات الإصدار في versions.json)
    DRY_RUN   «true» = تحقّقٌ فقط بلا نشر
    GH_TOKEN  رمز سير العمل (صلاحية issues: write)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "wwwrag80-create/gold_erp")
ISSUE = 23
MARK = "<!-- jadeite-mobile-channel -->"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/mobile/dist/"
PACKAGE = "com.jadeite.mobile"
# بصمة شهادة توقيع المالك (علنية — المفتاح نفسه خارج المستودع)
CERT_SHA256 = "aa0db0e3ac8dc3b27f285cc90c440bce8aceab0437c7cafc51dc01453ab0d465"
DIST = Path(__file__).resolve().parents[1] / "dist"


def summary(text):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def fail(msg):
    print("✘ " + msg)
    summary("### ❌ لم يُنشر شيء\n" + msg)
    sys.exit(1)


def build_tools():
    home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or ""
    root = Path(home, "build-tools")
    if not root.is_dir():
        fail("أدوات أندرويد (build-tools) غير موجودة في بيئة التشغيل")
    key = lambda p: [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", p.name)]
    for bt in sorted(root.iterdir(), key=key, reverse=True):
        if (bt / "aapt2").exists() and (bt / "apksigner").exists():
            return bt
    fail("لا aapt2 ولا apksigner في build-tools")


def apk_facts(apk):
    bt = build_tools()
    badging = subprocess.run([str(bt / "aapt2"), "dump", "badging", str(apk)],
                             capture_output=True, text=True).stdout
    m = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", badging)
    if not m:
        fail("تعذّرت قراءة بيانات الملف (aapt2)")
    v = subprocess.run([str(bt / "apksigner"), "verify", "--print-certs", str(apk)],
                       capture_output=True, text=True)
    if v.returncode != 0:
        fail("توقيع الملف غير سليم:\n" + (v.stderr or v.stdout)[-600:])
    certs = re.findall(r"certificate SHA-256 digest: ([0-9a-f]{64})", v.stdout)
    return m.group(1), int(m.group(2)), m.group(3), certs


def api(method, path, body=None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def current_pointer(body):
    i = body.find(MARK)
    a = body.find("```json", i) if i >= 0 else -1
    b = body.find("```", a + 7) if a >= 0 else -1
    if b < 0:
        return {}
    try:
        return json.loads(body[a + 7:b])
    except ValueError:
        return {}


def main():
    versions = json.loads((DIST / "versions.json").read_text(encoding="utf-8"))
    want = os.environ.get("VERSION", "").strip()
    if want:
        entry = next((v for v in versions if v.get("version") == want), None)
        if not entry:
            fail(f"الإصدار {want} ليس في mobile/dist/versions.json")
    else:
        entry = max(versions, key=lambda v: int(v.get("code", 0)))
    apk = DIST / entry["file"]
    if not re.fullmatch(r"[\w.\-]+\.apk", entry["file"]) or not apk.is_file():
        fail(f"الملف {entry['file']} غير موجود في mobile/dist")
    sha = hashlib.sha256(apk.read_bytes()).hexdigest()
    if sha != entry["sha256"]:
        fail("بصمة الملف لا تطابق versions.json")
    pkg, code, name, certs = apk_facts(apk)
    if pkg != PACKAGE:
        fail(f"اسم الحزمة {pkg} غير اسم التطبيق")
    if code != int(entry["code"]) or name != entry["version"]:
        fail(f"رقم الإصدار في الملف ({name} · {code}) غير ما في versions.json ({entry['version']} · {entry['code']})")
    if certs != [CERT_SHA256]:
        fail("الملف غير موقّعٍ بمفتاح المالك — لن يُثبَّت فوق التطبيق، فلم يُنشر")

    issue = api("GET", f"issues/{ISSUE}")
    cur = current_pointer(issue.get("body") or "")
    if int(cur.get("code") or 0) > code:
        fail(f"المنشور الآن ({cur.get('version')}) أحدث من {name} — لا رجوع إلى إصدارٍ أقدم")

    notes = (os.environ.get("NOTES", "").strip() or entry.get("notes", "")).replace("`", "'")
    pointer = {
        "channel": "jadeite-mobile", "version": name, "code": code, "sha256": sha,
        "url": RAW + entry["file"], "notes": notes,
        "published": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    body = ("قناة تحديثات تطبيق «نظام محاسبي للذهب» للجوال: يقرأ التطبيق هذا النص ليعرف آخر إصدارٍ منشور، "
            "فيُنزّله من ملفات المستودع (`mobile/dist`) ويعرض على صاحبه تثبيته.\n\n"
            "يكتب هذا النصَّ سيرُ العمل «نشر تحديث الجوال» (Actions) — فلا تعدّله يدوياً ولا تُغلق هذه الصفحة.\n\n"
            + MARK + "\n```json\n" + json.dumps(pointer, ensure_ascii=False) + "\n```\n")
    print(json.dumps(pointer, ensure_ascii=False, indent=1))
    was = f"{cur.get('version')} ({cur.get('code')})" if cur.get("code") else "لا شيء"
    if os.environ.get("DRY_RUN", "").lower() == "true":
        summary(f"### 🧪 تجربة فقط — لم يُنشر شيء\nالملف سليم: **{name}** (رقم {code})، موقّعٌ بمفتاح المالك.\n"
                f"المنشور الآن: {was}")
        print("✔ تجربة: الملف سليم — لم يُنشر شيء")
        return
    api("PATCH", f"issues/{ISSUE}", {"body": body})
    summary(f"### ✅ نُشر الإصدار {name}\nكان المنشور: {was}.\n"
            "يصل التنبيه كل جوالٍ عليه التطبيق عند فتحه أو خلال ساعاتٍ وهو متصل بالإنترنت؛ "
            "فيُنزّل التحديث ويطلب تثبيته بلمسة، وبياناته تبقى.")
    print(f"✔ نُشر {name} ({code})")


if __name__ == "__main__":
    main()
