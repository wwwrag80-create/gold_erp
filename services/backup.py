# -*- coding: utf-8 -*-
"""نسخة احتياطية آمنة عبر واجهة sqlite3.backup + الإبقاء على آخر N نسخ."""
import sqlite3
from datetime import datetime

import config


def backup_now() -> str:
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if not config.DB_PATH.exists():
        raise FileNotFoundError("قاعدة البيانات غير موجودة بعد")
    target = config.BACKUP_DIR / f"gold_erp_{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(str(config.DB_PATH))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    # الإبقاء على آخر النسخ فقط
    backups = sorted(config.BACKUP_DIR.glob("gold_erp_*.db"))
    for old in backups[:-config.BACKUP_KEEP_LAST]:
        try:
            old.unlink()
        except OSError:
            pass
    return str(target)
