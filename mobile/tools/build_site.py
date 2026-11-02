"""يبني موقع ÀUR (رابط نسخة الآيفون) في مجلدٍ واحد يُنشر كما هو على GitHub Pages:

    python3 mobile/tools/build_site.py OUT_DIR

- الجذر: صفحة التثبيت (mobile/site/index.html) وسياسة الخصوصية وملفا ads.txt/app-ads.txt.
- app/: التطبيق نفسه (mobile/web) يعمل من الشاشة الرئيسية وبلا إنترنت؛ sw.js يُكتب فيه رقم
  الإصدار وقائمة الملفات (فيُنزَّل الإصدار الجديد وينتظر «حدّث الآن»).
- رابط تطبيق أندرويد: آخر إصدارٍ منشور في mobile/dist/versions.json.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]           # mobile/
REPO = "wwwrag80-create/gold_erp"


def main(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    ver = json.loads((ROOT / "web" / "version.json").read_text(encoding="utf-8"))
    dist = json.loads((ROOT / "dist" / "versions.json").read_text(encoding="utf-8"))
    apk = dist[-1]
    apk_url = f"https://raw.githubusercontent.com/{REPO}/main/mobile/dist/{apk['file']}"

    # التطبيق
    app = out / "app"
    shutil.copytree(ROOT / "web", app)
    files = sorted(p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file() and p.name != "sw.js")
    # بصمة الملفات: أي تغييرٍ فيها = نسخةٌ جديدة تصل الآيفون («يوجد تحديث جديد»)
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode()); h.update((app / f).read_bytes())
    sw = (app / "sw.js").read_text(encoding="utf-8")
    assert 'const VERSION = "dev";' in sw and "const FILES = [];" in sw
    sw = sw.replace('const VERSION = "dev";', f'const VERSION = {json.dumps(ver["name"] + "-" + h.hexdigest()[:10])};')
    sw = sw.replace("const FILES = [];", "const FILES = " + json.dumps(["./"] + files, ensure_ascii=False) + ";")
    (app / "sw.js").write_text(sw, encoding="utf-8")

    # الصفحات
    for name in ("index.html", "privacy.html"):
        html = (ROOT / "site" / name).read_text(encoding="utf-8")
        html = (html.replace("{{APK_URL}}", apk_url).replace("{{APK_VERSION}}", apk["version"])
                .replace("{{WEB_VERSION}}", ver["name"]))
        assert "{{" not in html, name
        (out / name).write_text(html, encoding="utf-8")
    for name in ("ads.txt", "app-ads.txt"):
        shutil.copy(ROOT / "site" / name, out / name)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"✔ {out} — الويب {ver['name']} · أندرويد {apk['version']} · {len(files)} ملفاً في app/")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "site-out"))
