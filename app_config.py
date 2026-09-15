# -*- coding: utf-8 -*-
"""قارئ الإعدادات — الملف الفعلي في مجلد core."""
from core.app_config import *      # noqa: F401,F403
from core.app_config import (ENV_FILE, get, reload, write_env,  # noqa: F401
                             supabase_url, supabase_key,
                             supabase_service_key)
