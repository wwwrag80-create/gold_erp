# تحويل النظام إلى ملف تشغيل واحد (Windows exe)

```bash
pip install pyinstaller PyQt5 python-barcode qrcode Pillow
pyinstaller --onefile --windowed --name GoldERP main.py
```

- الناتج: `dist/GoldERP.exe`
- قاعدة البيانات `gold_erp.db` ومجلدا `backups/` و`assets/` تُنشأ تلقائياً
  بجوار ملف exe عند أول تشغيل (المسارات نسبية لمجلد التشغيل).
- لإضافة أيقونة: `--icon=assets/icon.ico`
