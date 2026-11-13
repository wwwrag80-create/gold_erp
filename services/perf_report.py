# -*- coding: utf-8 -*-
"""تقرير الأداء للدعم (5.3.6) — ما يحتاجه من يشخّص بطءاً على جهاز العميل.

«النظام يعلق» جملةٌ واحدة لأسبابٍ مختلفة: قاعدةٌ كبرت، قرصٌ بطيء أو ممتلئ،
مجلدٌ تحت مزامنة OneDrive، صورٌ ضخمة، أو موضعٌ في البرنامج نفسه. التقرير
يجمع الأرقام كلها مع آخر ما رصده حارس التجمّد بمواضعه — نصّاً يُنسخ
ويُرسل كما هو. لا يحوي أسماء عملاء ولا أرقاماً مالية.
"""
import os
import platform
import shutil
import sys
from pathlib import Path


def _mb(n):
    return f"{n / (1024 * 1024):,.1f} MB"


def _dir_size(d, pattern="*"):
    total = count = 0
    try:
        for f in Path(d).glob(pattern):
            if f.is_file():
                total += f.stat().st_size
                count += 1
    except Exception:
        pass
    return count, total


def _ram_text():
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return (f"{m.ullTotalPhys / 2**30:.1f} GB، المتاح "
                    f"{m.ullAvailPhys / 2**30:.1f} GB ({m.dwMemoryLoad}% مستعمل)")
        info = dict(line.split(":", 1) for line in open("/proc/meminfo")
                    if ":" in line)
        tot = int(info["MemTotal"].split()[0]) / 2**20
        av = int(info.get("MemAvailable", "0 kB").split()[0]) / 2**20
        return f"{tot:.1f} GB، المتاح {av:.1f} GB"
    except Exception:
        return "—"


def _proc_mb():
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD),
                            ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            c = PMC()
            c.cb = ctypes.sizeof(PMC)
            h = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c),
                                                     c.cb)
            return _mb(c.WorkingSetSize)
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS"):
                return _mb(int(line.split()[1]) * 1024)
    except Exception:
        pass
    return "—"


def slow_lines(n=40):
    """آخر أسطر البطء والتجمّد من سجل النظام."""
    try:
        from services import health
        p = health._log_path()
        if not p.exists():
            return []
        out = [ln.rstrip() for ln in p.read_text(
            encoding="utf-8", errors="replace").splitlines()
            if "بطء:" in ln or "تجمّد" in ln or ln.startswith("      ")]
        return out[-n:]
    except Exception:
        return []


def build():
    """نصّ التقرير."""
    import config
    from database.database import db
    L = []
    add = L.append
    add(f"تقرير الأداء — {config.APP_NAME} {config.APP_VERSION}")
    add(f"النظام: {platform.platform()} · معالجات: {os.cpu_count()}")
    add(f"الذاكرة: {_ram_text()} · البرنامج يستعمل {_proc_mb()}")
    frozen = getattr(sys, "frozen", False)
    add("التشغيل: " + ("ملف exe واحد (يُفكّ مع كل تشغيل)"
                       if frozen and getattr(sys, "_MEIPASS", None)
                       else "ملف exe" if frozen else "من المصدر"))
    dbp = Path(str(config.DB_PATH))
    add(f"مجلد البيانات: {dbp.parent}")
    low = str(dbp).lower()
    if "onedrive" in low or "dropbox" in low or "google drive" in low:
        add("⚠ مجلد البيانات داخل مجلدٍ تُزامنه خدمة سحابية — يُبطئ الحفظ"
            " ويقفل الملف أحياناً")
    try:
        add(f"حجم القاعدة: {_mb(dbp.stat().st_size)}")
        wal = Path(str(dbp) + "-wal")
        if wal.exists():
            add(f"ملف WAL: {_mb(wal.stat().st_size)}"
                + ("  ⚠ كبير — يُدمج في الصيانة" if wal.stat().st_size
                   > 64 * 1024 * 1024 else ""))
    except Exception:
        pass
    try:
        du = shutil.disk_usage(str(dbp.parent))
        add(f"القرص: الفارغ {du.free / 2**30:.1f} GB من {du.total / 2**30:.0f} GB"
            + ("  ⚠ أقل من 5 GB" if du.free < 5 * 2**30 else ""))
    except Exception:
        pass
    try:
        from models import models_catalog as mc
        n, sz = 0, 0
        for f in mc.images_dir().iterdir():
            if f.suffix.lower() in mc.IMAGE_EXTS:
                n += 1
                sz += f.stat().st_size
        add(f"صور الموديلات: {n} صورة · {_mb(sz)}"
            + (f" · متوسط {_mb(sz / n)}" if n else ""))
    except Exception:
        pass
    try:
        from services import storage
        bd = storage.backup_dir()
        n, sz = _dir_size(bd, "*.bak")
        add(f"النسخ الاحتياطية: {n} نسخة · {_mb(sz)} في {bd}")
    except Exception:
        pass
    try:
        with db(readonly=True) as conn:
            parts = []
            for t, lbl in (("work_orders", "أطقم"), ("invoices", "فواتير"),
                           ("journal_entries", "قيود"),
                           ("journal_lines", "أسطر قيود"),
                           ("audit_log", "سجل العمليات")):
                try:
                    k = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    parts.append(f"{lbl} {k:,}")
                except Exception:
                    pass
            add("البيانات: " + " · ".join(parts))
            try:
                from services import models_web
                st = models_web.settings(conn)
                add("رابط المدير: " + ("مفعّل" if st["enabled"] else "موقوف"))
            except Exception:
                pass
    except Exception as e:
        add(f"تعذّرت قراءة القاعدة: {e}")
    try:
        from services import ui_watchdog
        st = ui_watchdog.stalls()
        add(f"تجمّد الواجهة في هذه الجلسة: {st.get('count', 0)} مرة"
            + (" — " + " · ".join(st.get("places", [])[:3])
               if st.get("count") else ""))
    except Exception:
        pass
    lines = slow_lines()
    add("")
    add("آخر ما رُصد من بطءٍ وتجمّد (بموضعه في البرنامج):")
    L.extend(lines or ["— لم يُرصد شيء —"])
    return "\n".join(L)
