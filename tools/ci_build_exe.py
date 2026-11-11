# -*- coding: utf-8 -*-
"""بناءٌ تجريبي للملف التنفيذي في GitHub Actions (ويندوز) — للفحص لا للتوزيع.

يبني بأداة البناء نفسها (`core/build.py`) وبالمكتبات نفسها التي يثبّتها
`MAKE_EXE.bat`، لكن **بلا إعدادات السحابة** (لا ملف .env على المشغّل)؛ فالملف
الناتج لا يصلح لتسجيل دخول المصانع ولا يُوزَّع. غرضه أن يثبت على ويندوز
نفسه أن محرّك الويب يُضمّ في الملف الواحد وأن مشهد الدخول يُحمَّل منه.

    python tools/ci_build_exe.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.build as b  # noqa: E402

b._bundled_env = lambda: None
b.build_app(onefile=True)
