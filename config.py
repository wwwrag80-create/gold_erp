# -*- coding: utf-8 -*-
"""ثوابت النظام — الملف الفعلي في مجلد core."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))
from core.config import *          # noqa: F401,F403,E402
from core.config import (BASE_DIR, BUNDLE_DIR, DB_PATH,  # noqa: F401,E402
                         BACKUP_DIR, BARCODE_DIR, ICONS_DIR,
                         APP_NAME, APP_VERSION, BUILD_STAMP)
