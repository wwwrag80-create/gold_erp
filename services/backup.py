# -*- coding: utf-8 -*-
"""زر «💾 نسخة» — واجهةٌ رفيعة فوق نظام النسخ الوحيد في `storage`.

كانت هنا آلية نسخٍ ثالثة بمجلدها وعددها الخاص؛ توحّدت (4.29) فصار
للمصنع مجلد نسخٍ واحد، وآخر 20 نسخة، وقائمة استرجاعٍ واحدة.
"""


def backup_now() -> str:
    from services import storage
    path = storage.make_backup("manual")
    if not path:
        raise FileNotFoundError("قاعدة البيانات غير موجودة بعد")
    return path
