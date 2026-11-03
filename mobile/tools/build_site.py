"""يبني موقع ÀUR (رابط نسخة الآيفون) في مجلدٍ واحد يُنشر كما هو (Cloudflare Pages، وNetlify قبله):

    python3 mobile/tools/build_site.py OUT_DIR

- الجذر: صفحة التثبيت (mobile/site/index.html) وسياسة الخصوصية وملفا ads.txt/app-ads.txt.
- app/: التطبيق نفسه (mobile/web) يعمل من الشاشة الرئيسية وبلا إنترنت؛ sw.js يُكتب فيه رقم
  الإصدار وقائمة الملفات (فيُنزَّل الإصدار الجديد وينتظر «حدّث الآن»).
- تطبيق أندرويد: آخر إصدارٍ منشور (mobile/dist/versions.json) يُنسخ إلى الموقع باسم AUR.apk. وحين يُنشر
  في Google Play (site/config.json ← "play_live": true) يصير زرّ أندرويد رابط المتجر، والملف بديلاً تحته.
"""
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]           # mobile/


def moved_site(out: Path, to: str) -> None:
    """الموقع انتقل (site/config.json ← moved_to): كل رابطٍ قديم يُحوَّل إلى مكانه نفسه في الموقع الجديد —
    تحويلٌ من الخادم (301) فلا صفحة تُعرض هنا، ولا شعار استضافة."""
    to = to.rstrip("/")
    (out / "_redirects").write_text(f"/*  {to}/:splat  301!\n", encoding="utf-8")
    (out / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={to}/">'
        f'<title>ÀUR</title><a href="{to}/">ÀUR</a>\n', encoding="utf-8")
    print(f"✔ {out} — تحويلٌ إلى {to}")


def main(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cfg = json.loads((ROOT / "site" / "config.json").read_text(encoding="utf-8"))
    # على Netlify (المكان القديم) بعد الانتقال: تحويلٌ وحده. والمكان الجديد يُبنى كاملاً كالعادة
    if cfg.get("moved_to") and os.environ.get("NETLIFY") == "true":
        moved_site(out, cfg["moved_to"])
        return
    ver = json.loads((ROOT / "web" / "version.json").read_text(encoding="utf-8"))
    dist = json.loads((ROOT / "dist" / "versions.json").read_text(encoding="utf-8"))
    apk = dist[-1]
    apk_url = "AUR.apk"     # ملف أندرويد من الموقع نفسه — رابطٌ واحد للجميع

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

    # الصفحات — أندرويد: ملف التثبيت، أو Google Play حين يُنشر فيه (site/config.json: play_live)
    keep, drop = ("play", "apk") if cfg.get("play_live") else ("apk", "play")
    for name in ("index.html", "privacy.html"):
        html = (ROOT / "site" / name).read_text(encoding="utf-8")
        html = re.sub(rf"<!--{drop}-->.*?<!--/{drop}-->", "", html, flags=re.S)
        html = html.replace(f"<!--{keep}-->", "").replace(f"<!--/{keep}-->", "")
        html = (html.replace("{{APK_URL}}", apk_url).replace("{{APK_VERSION}}", apk["version"])
                .replace("{{WEB_VERSION}}", ver["name"]).replace("{{PLAY_URL}}", cfg["play_url"]))
        assert "{{" not in html, name
        (out / name).write_text(html, encoding="utf-8")
    for name in ("ads.txt", "app-ads.txt"):
        shutil.copy(ROOT / "site" / name, out / name)
    shutil.copy(ROOT / "dist" / apk["file"], out / "AUR.apk")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    # Netlify: نوع ملف التطبيق الصحيح، وعامل الخدمة يُفحص كل مرة (فيصل التحديث فوراً)
    (out / "_headers").write_text(
        "/app/manifest.webmanifest\n  Content-Type: application/manifest+json\n"
        "/app/sw.js\n  Cache-Control: no-cache\n", encoding="utf-8")
    print(f"✔ {out} — الويب {ver['name']} · أندرويد {apk['version']} · {len(files)} ملفاً في app/")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "site-out"))
