"""إعلانات تطبيق الجوال (الرعاة) — من GitHub، بلا تحديثٍ للتطبيق.

يحرّر `mobile/promo/promo.json` الذي يقرؤه التطبيق كل 6 ساعات:
  - بطاقة راعٍ في الرئيسية (مصنعٌ أو مورّدٌ يدفع لصاحب التطبيق)،
  - سطر التعريف أسفل المستندات المُرسَلة،
  - رقم التواصل في «أعلن في التطبيق».

يُشغّله سير العمل «إعلانات التطبيق» (`.github/workflows/mobile-promo.yml`)
بخاناتٍ في نموذج (البيئة): ACTION · TITLE · TEXT · PHONE · LINK · DAYS · AD_ID ·
FOOTER · CONTACT. ثم يحفظ الملف ويرسله إلى main.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "promo" / "promo.json"


def env(k, n=300):
    return re.sub(r"\s+", " ", os.environ.get(k, "")).strip()[:n]


def summary(text):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def fail(msg):
    print("✘ " + msg)
    summary("### ❌ لم يتغيّر شيء\n" + msg)
    sys.exit(1)


def phone(x):
    d = re.sub(r"\D", "", x or "")
    if d and not 8 <= len(d) <= 15:
        fail(f"رقم الجوال غير صحيح: {x}")
    return d


def wa(d):
    # 05xxxxxxxx ← 9665xxxxxxxx لواتساب
    return "966" + d[1:] if d.startswith("05") else d


def main():
    data = json.loads(FILE.read_text(encoding="utf-8"))
    items = data.get("items") or []
    action = env("ACTION", 60)
    now = datetime.now(timezone.utc)
    if action.startswith("إضافة"):
        title = env("TITLE", 60)
        if not title:
            fail("اكتب عنوان الإعلان (اسم المصنع أو النشاط)")
        link = env("LINK", 300)
        if link and not re.fullmatch(r"https://[^\s\"'<>]+", link):
            fail("الرابط يجب أن يبدأ بـ https://")
        ph = phone(env("PHONE", 20))
        try:
            days = max(1, min(366, int(env("DAYS", 4) or "30")))
        except ValueError:
            fail("المدة بالأيام رقمٌ فقط")
        ad = {"id": "ad-" + now.strftime("%y%m%d%H%M%S"), "title": title, "text": env("TEXT", 220),
              "phone": ph, "whatsapp": wa(ph), "link": link,
              "until": (now + timedelta(days=days)).strftime("%Y-%m-%d")}
        items.append(ad)
        msg = f"أُضيف إعلان «{title}» حتى {ad['until']} (رقمه {ad['id']})."
    elif action.startswith("حذف كل"):
        msg = f"حُذفت كل الإعلانات ({len(items)})."
        items = []
    elif action.startswith("حذف"):
        key = env("AD_ID", 60) or env("TITLE", 60)
        if not key:
            fail("اكتب رقم الإعلان أو عنوانه في خانته")
        left = [x for x in items if x.get("id") != key and x.get("title") != key]
        if len(left) == len(items):
            fail(f"لا إعلان بالرقم أو العنوان: {key}")
        msg = f"حُذف الإعلان «{key}»."
        items = left
    elif action.startswith("بيانات"):
        footer = env("FOOTER", 120)
        if footer == "-":
            data["footer"] = ""
        elif footer:
            data["footer"] = footer
        ph = phone(env("CONTACT", 20))
        if ph:
            data["contact"] = {"name": "", "phone": ph, "whatsapp": wa(ph), "text": env("TEXT", 220)}
        elif env("CONTACT", 20) == "-":
            data["contact"] = None
        msg = "حُفظت بيانات التواصل وسطر التعريف."
    else:
        fail(f"إجراءٌ غير معروف: {action}")
    # الإعلانات المنتهية تُحذف تلقائياً
    today = now.strftime("%Y-%m-%d")
    items = [x for x in items if not x.get("until") or x["until"] >= today]
    data.update({"channel": "jadeite-promo", "items": items, "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    lines = [f"- **{x['title']}** — حتى {x.get('until') or 'دائم'} — رقمه `{x['id']}`" for x in items] or ["- لا إعلانات الآن"]
    summary(f"### ✅ {msg}\nيظهر في التطبيقات خلال ساعات (عند فتحها وهي متصلة).\n\n**الإعلانات الآن:**\n" + "\n".join(lines) +
            f"\n\n**سطر التعريف:** {data.get('footer') or '(لا شيء)'}\n**رقم التواصل:** {(data.get('contact') or {}).get('phone') or '(لا شيء)'}")
    print("✔ " + msg)


if __name__ == "__main__":
    main()
