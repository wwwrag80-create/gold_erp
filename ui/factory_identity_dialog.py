# -*- coding: utf-8 -*-
"""حوار «هوية المصنع» — يُفتح من زر «عرض».

صورة الشعار واسم المصنع وبلده وعنوانه وسجله أمام المستخدم، ومعاينةٌ
حيّة للترويسة كما ستُطبع تتغيّر مع كل حرف. عند «اعتماد» تُحفظ في
قاعدة هذا المصنع وتتبدّل فوراً في جميع قوالب الطباعة وفي الواجهة.

النسخة نفسها تُسلَّم لمصنعٍ آخر فيضع هويته هنا — أو يستورد ملف
الهوية الذي صدّره صاحبه — فتخرج أوراقه باسمه وشعاره لا باسم غيره.
"""
import base64

from PyQt5 import QtCore, QtGui, QtWidgets

from database.database import db
from services import branding
from ui.widgets.common import ask, err, info

IMG_FILTER = "صور (*.png *.jpg *.jpeg *.bmp *.webp)"
MAX_SIDE = 700          # يكفي لطباعة حادّة ولا يُثقل القاعدة


def image_to_b64(path, max_side=MAX_SIDE):
    """يقرأ الصورة ويصغّرها بتناسبها ويعيدها PNG بترميز base64.

    الشفافية تبقى كما هي (PNG)، والصورة الكبيرة من الهاتف (4000 بكسل)
    تُصغَّر — فلا تثقل القاعدة ولا النسخ الاحتياطية.
    """
    img = QtGui.QImage(str(path))
    if img.isNull():
        raise ValueError("تعذّر فتح الصورة — اختر ملف PNG أو JPG")
    if max(img.width(), img.height()) > max_side:
        img = img.scaled(max_side, max_side, QtCore.Qt.KeepAspectRatio,
                         QtCore.Qt.SmoothTransformation)
    buf = QtCore.QBuffer()
    buf.open(QtCore.QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return base64.b64encode(bytes(buf.data())).decode("ascii")


def _pix_from_b64(b64):
    pix = QtGui.QPixmap()
    if b64:
        pix.loadFromData(base64.b64decode(b64))
    return pix


class FactoryIdentityDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, user=None):
        super().__init__(parent)
        self.user = user or {}
        self.setObjectName("identityDialog")
        self.setWindowTitle("هوية المصنع — الشعار والاسم والعنوان في "
                            "جميع قوالب الطباعة")
        self.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.resize(1180, 820)
        self._logo_b64 = ""
        self._stamp_b64 = ""
        self.applied = False
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self._refresh_preview)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(10)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(self._images_box(), 0)
        top.addWidget(self._fields_box(), 1)
        lay.addLayout(top)
        lay.addWidget(self._preview_box(), 1)
        lay.addLayout(self._buttons())

        with db(readonly=True) as conn:
            self._custom = branding.is_custom(conn)
            data = branding.load(conn)
        if not self._custom or branding.is_blank(data):
            # أول ضبط (ومنه هوية المصنع الجديد الفارغة): الشعار يساراً
            data["layout"] = "logo_left"
        self.set_data(data)
        self._editable = self._can_edit()
        if not self._editable:
            for w in (list(self.f.values()) + list(self.layout_btns.values())
                      + [self.hide_logo, self.logo_size, self.show_en,
                         self.show_vat, self.btn_logo, self.btn_logo_clear,
                         self.btn_stamp, self.btn_stamp_clear,
                         self.btn_apply, self.btn_import, self.btn_reset]):
                w.setEnabled(False)
            self.note.setText("🔒 تعديل هوية المصنع للمدير وحده — "
                              "المعروض هو المعتمد حالياً.")
            self.note.show()

    def _can_edit(self):
        # مستخدم المبيعات يرى الهوية ولا يغيّرها؛ المحاسب (صاحب النظام)
        # ومدير السحابة يعتمدانها
        return (self.user.get("role_local", "accountant") != "sales"
                or self.user.get("role") == "super_admin")

    # ══════════ الصور ══════════
    def _images_box(self):
        box = QtWidgets.QGroupBox("الشعار والختم")
        box.setFixedWidth(330)
        v = QtWidgets.QVBoxLayout(box)
        self.logo_view = QtWidgets.QLabel()
        self.logo_view.setObjectName("identityLogo")
        self.logo_view.setAlignment(QtCore.Qt.AlignCenter)
        self.logo_view.setFixedSize(300, 190)
        self.logo_view.setStyleSheet(
            "QLabel#identityLogo { border: 1px dashed #C9A227;"
            " border-radius: 8px; background: #FFFFFF; color: #8A7A55; }")
        v.addWidget(self.logo_view, 0, QtCore.Qt.AlignHCenter)
        row = QtWidgets.QHBoxLayout()
        self.btn_logo = QtWidgets.QPushButton("🖼 اختيار الشعار…")
        self.btn_logo.clicked.connect(self.pick_logo)
        self.btn_logo_clear = QtWidgets.QPushButton("الشعار الأصلي")
        self.btn_logo_clear.setToolTip("يعيد الشعار المرفق مع النظام")
        self.btn_logo_clear.clicked.connect(self.clear_logo)
        row.addWidget(self.btn_logo)
        row.addWidget(self.btn_logo_clear)
        v.addLayout(row)
        self.hide_logo = QtWidgets.QCheckBox("بلا شعار في الطباعة")
        self.hide_logo.toggled.connect(self._changed)
        v.addWidget(self.hide_logo)
        f = QtWidgets.QFormLayout()
        self.logo_size = QtWidgets.QComboBox()
        for px, label in branding.LOGO_SIZES:
            self.logo_size.addItem(label, px)
        self.logo_size.currentIndexChanged.connect(self._changed)
        f.addRow("حجم الشعار:", self.logo_size)
        v.addLayout(f)

        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        v.addWidget(sep)
        self.stamp_view = QtWidgets.QLabel()
        self.stamp_view.setObjectName("identityStamp")
        self.stamp_view.setAlignment(QtCore.Qt.AlignCenter)
        self.stamp_view.setFixedSize(300, 100)
        self.stamp_view.setStyleSheet(
            "QLabel#identityStamp { border: 1px dashed #BDB29A;"
            " border-radius: 8px; background: #FFFFFF; color: #8A7A55; }")
        v.addWidget(self.stamp_view, 0, QtCore.Qt.AlignHCenter)
        row2 = QtWidgets.QHBoxLayout()
        self.btn_stamp = QtWidgets.QPushButton("🔏 ختم / توقيع…")
        self.btn_stamp.setToolTip("صورة الختم تظهر بجوار «التوقيع» "
                                  "أسفل كل ورقة (اختياري)")
        self.btn_stamp.clicked.connect(self.pick_stamp)
        self.btn_stamp_clear = QtWidgets.QPushButton("إزالة الختم")
        self.btn_stamp_clear.clicked.connect(self.clear_stamp)
        row2.addWidget(self.btn_stamp)
        row2.addWidget(self.btn_stamp_clear)
        v.addLayout(row2)
        v.addStretch(1)
        return box

    # ══════════ البيانات ══════════
    def _fields_box(self):
        box = QtWidgets.QGroupBox("بيانات المصنع كما تُطبع")
        g = QtWidgets.QGridLayout(box)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)

        def edit(ph="", ltr=False):
            e = QtWidgets.QLineEdit()
            e.setPlaceholderText(ph)
            e.setMinimumHeight(34)
            if ltr:
                e.setLayoutDirection(QtCore.Qt.LeftToRight)
                e.setAlignment(QtCore.Qt.AlignLeft)
            e.textChanged.connect(self._changed)
            return e

        self.f = {
            "name": edit("مثال: مصنع النخبة للذهب"),
            "name_en": edit("Factory name", True),
            "country": edit("المملكة العربية السعودية"),
            "country_en": edit("Saudi Arabia, Riyadh", True),
            "address": edit("المدينة — الحي / الشارع"),
            "address_en": edit("Industrial City", True),
            "cr": edit("رقم السجل التجاري", True),
            "vat": edit("15 رقماً يبدأ وينتهي بـ 3", True),
            "phone": edit("05xxxxxxxx", True),
            "email": edit("info@example.com", True),
            "tagline": edit("للذهب والمجوهرات"),
        }
        hdr_ar = QtWidgets.QLabel("<b>بالعربية</b>")
        hdr_en = QtWidgets.QLabel("<b>English</b>")
        g.addWidget(hdr_ar, 0, 1)
        g.addWidget(hdr_en, 0, 2)
        rows = (("اسم المصنع *", "name", "name_en"),
                ("البلد", "country", "country_en"),
                ("العنوان", "address", "address_en"))
        r = 1
        for label, ar, en_ in rows:
            g.addWidget(QtWidgets.QLabel(label), r, 0)
            g.addWidget(self.f[ar], r, 1)
            g.addWidget(self.f[en_], r, 2)
            r += 1
        for (l1, k1), (l2, k2) in ((("السجل التجاري", "cr"),
                                    ("الرقم الضريبي", "vat")),
                                   (("الهاتف", "phone"),
                                    ("البريد", "email"))):
            g.addWidget(QtWidgets.QLabel(l1), r, 0)
            g.addWidget(self.f[k1], r, 1)
            pair = QtWidgets.QHBoxLayout()
            pair.addWidget(QtWidgets.QLabel(l2))
            pair.addWidget(self.f[k2], 1)
            g.addLayout(pair, r, 2)
            r += 1
        g.addWidget(QtWidgets.QLabel("العبارة التعريفية"), r, 0)
        g.addWidget(self.f["tagline"], r, 1, 1, 2)
        r += 1

        lay_box = QtWidgets.QGroupBox("ترتيب الترويسة")
        lv = QtWidgets.QVBoxLayout(lay_box)
        self.layout_group = QtWidgets.QButtonGroup(self)
        self.layout_btns = {}
        for key, label in branding.LAYOUTS:
            rb = QtWidgets.QRadioButton(label)
            rb.toggled.connect(self._changed)
            self.layout_group.addButton(rb)
            self.layout_btns[key] = rb
            lv.addWidget(rb)
        opts = QtWidgets.QHBoxLayout()
        self.show_en = QtWidgets.QCheckBox("إظهار الاسم الإنجليزي")
        self.show_en.toggled.connect(self._changed)
        self.show_vat = QtWidgets.QCheckBox("إظهار الرقم الضريبي تحت السجل")
        self.show_vat.toggled.connect(self._changed)
        opts.addWidget(self.show_en)
        opts.addWidget(self.show_vat)
        opts.addStretch(1)
        lv.addLayout(opts)
        g.addWidget(lay_box, r, 0, 1, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 1)
        return box

    def _preview_box(self):
        box = QtWidgets.QGroupBox("معاينة الترويسة كما ستُطبع")
        v = QtWidgets.QVBoxLayout(box)
        self.note = QtWidgets.QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color:#8A1010; font-weight:bold;")
        self.note.hide()
        v.addWidget(self.note)
        self.preview = QtWidgets.QTextBrowser()
        self.preview.setObjectName("identityPreview")
        self.preview.setMinimumHeight(230)
        self.preview.setStyleSheet(
            "QTextBrowser#identityPreview { background: #FFFFFF;"
            " color: #1a1a1a; border: 1px solid #D8CDB4;"
            " border-radius: 6px; padding: 10px; }")
        v.addWidget(self.preview)
        return box

    def _buttons(self):
        h = QtWidgets.QHBoxLayout()
        self.btn_apply = QtWidgets.QPushButton("✔ اعتماد الهوية")
        self.btn_apply.setObjectName("primary")
        self.btn_apply.setMinimumHeight(40)
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self.apply)
        self.btn_import = QtWidgets.QPushButton("⬇ استيراد ملف هوية…")
        self.btn_import.clicked.connect(self.import_identity)
        self.btn_export = QtWidgets.QPushButton("⬆ تصدير ملف الهوية…")
        self.btn_export.setToolTip("ملفٌ واحد يحمل الشعار والبيانات — "
                                   "يُستورد في جهازٍ آخر للمصنع نفسه")
        self.btn_export.clicked.connect(self.export_identity)
        self.btn_reset = QtWidgets.QPushButton("↺ الهوية الأصلية")
        self.btn_reset.clicked.connect(self.reset_identity)
        self.btn_close = QtWidgets.QPushButton("إغلاق")
        self.btn_close.clicked.connect(self.reject)
        h.addWidget(self.btn_apply)
        h.addWidget(self.btn_import)
        h.addWidget(self.btn_export)
        h.addWidget(self.btn_reset)
        h.addStretch(1)
        h.addWidget(self.btn_close)
        return h

    # ══════════ القيم ══════════
    def set_data(self, d):
        self._loading = True
        try:
            for k, e in self.f.items():
                e.setText(str(d.get(k) or ""))
            self._logo_b64 = d.get("logo_b64") or ""
            self._stamp_b64 = d.get("stamp_b64") or ""
            self.hide_logo.setChecked(bool(d.get("hide_logo")))
            i = self.logo_size.findData(int(d.get("logo_h") or 120))
            if i < 0:
                self.logo_size.addItem(f"{d.get('logo_h')} بكسل",
                                       int(d.get("logo_h") or 120))
                i = self.logo_size.count() - 1
            self.logo_size.setCurrentIndex(i)
            btn = self.layout_btns.get(d.get("layout")) or \
                self.layout_btns["logo_left"]
            btn.setChecked(True)
            self.show_en.setChecked(bool(d.get("show_en", True)))
            self.show_vat.setChecked(bool(d.get("show_vat")))
        finally:
            self._loading = False
        self._show_images()
        self._refresh_preview()

    def data(self):
        d = {k: e.text().strip() for k, e in self.f.items()}
        d["logo_b64"] = self._logo_b64
        d["stamp_b64"] = self._stamp_b64
        d["hide_logo"] = self.hide_logo.isChecked()
        d["logo_h"] = self.logo_size.currentData() or 120
        d["layout"] = next((k for k, b in self.layout_btns.items()
                            if b.isChecked()), "logo_left")
        d["show_en"] = self.show_en.isChecked()
        d["show_vat"] = self.show_vat.isChecked()
        return d

    def _changed(self, *_a):
        if not getattr(self, "_loading", False):
            self._timer.start()

    def _show_images(self):
        pix = _pix_from_b64(self._logo_b64)
        if pix.isNull():
            import config
            p = branding._ORIG.get("LOGO_PATH") or \
                getattr(config, "LOGO_PATH", None)
            pix = QtGui.QPixmap(str(p)) if p else QtGui.QPixmap()
        if self.hide_logo.isChecked() or pix.isNull():
            self.logo_view.setPixmap(QtGui.QPixmap())
            self.logo_view.setText("بلا شعار" if self.hide_logo.isChecked()
                                   else "لم يُختر شعار")
        else:
            self.logo_view.setPixmap(pix.scaled(
                280, 170, QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation))
        sp = _pix_from_b64(self._stamp_b64)
        if sp.isNull():
            self.stamp_view.setPixmap(QtGui.QPixmap())
            self.stamp_view.setText("بلا ختم (اختياري)")
        else:
            self.stamp_view.setPixmap(sp.scaled(
                280, 90, QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation))

    def _refresh_preview(self):
        self._show_images()
        try:
            from services import print_fonts
            from services import print_manager as pm
            head, foot = branding.preview_html(self.data())
            css = pm.BASE_CSS.replace("@FAMILY@", print_fonts.family_css())
            sample = ('<table class="titlebar" width="100%" cellspacing="0"'
                      ' cellpadding="6"><tr><td width="100%">'
                      'فاتورة مبيعات — نموذج</td></tr></table>')
            self.preview.setHtml(f"{css}<div dir='rtl'>{head}{sample}"
                                 f"{foot}</div>")
        except Exception as e:                        # noqa: BLE001
            self.preview.setPlainText(f"تعذّرت المعاينة: {e}")
        errs = branding.validate(self.data())
        if getattr(self, "_editable", True):
            self.note.setVisible(bool(errs))
            self.note.setText("⚠ " + " · ".join(errs) if errs else "")
            self.btn_apply.setEnabled(not errs)

    # ══════════ الأفعال ══════════
    def _pick(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self, "اختيار صورة", "", IMG_FILTER)
        if not path:
            return None
        try:
            return image_to_b64(path)
        except Exception as e:                        # noqa: BLE001
            err(self, e)
            return None

    def pick_logo(self):
        b = self._pick()
        if b:
            self._logo_b64 = b
            self.hide_logo.setChecked(False)
            self._refresh_preview()

    def clear_logo(self):
        self._logo_b64 = ""
        self._refresh_preview()

    def pick_stamp(self):
        b = self._pick()
        if b:
            self._stamp_b64 = b
            self._refresh_preview()

    def clear_stamp(self):
        self._stamp_b64 = ""
        self._refresh_preview()

    def apply(self):
        d = self.data()
        errs = branding.validate(d)
        if errs:
            err(self, "\n".join(errs))
            return
        try:
            with db() as conn:
                branding.save(conn, d, self.user.get("username"))
        except Exception as e:                        # noqa: BLE001
            err(self, e)
            return
        self.applied = True
        self._custom = True
        info(self, f"اعتُمدت هوية «{d['name']}».\n\n"
                   "تظهر من الآن في جميع قوالب الطباعة وفي واجهة النظام.")
        self.accept()

    def reset_identity(self):
        if not ask(self, "إعادة الهوية الأصلية المرفقة مع النظام؟\n\n"
                         "يُحذف الشعار والبيانات التي أُدخلت هنا."):
            return
        try:
            with db() as conn:
                d = branding.reset(conn, self.user.get("username"))
        except Exception as e:                        # noqa: BLE001
            err(self, e)
            return
        self.applied = True
        self._custom = False
        d["layout"] = "logo_left"
        self.set_data(d)

    def export_identity(self):
        path, _f = QtWidgets.QFileDialog.getSaveFileName(
            self, "تصدير ملف الهوية",
            f"هوية_{(self.f['name'].text() or 'المصنع').replace(' ', '_')}"
            ".identity.json", "ملف هوية (*.json)")
        if not path:
            return
        try:
            branding.export_file(path, self.data())
            info(self, f"صُدّرت الهوية إلى:\n{path}")
        except Exception as e:                        # noqa: BLE001
            err(self, e)

    def import_identity(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self, "استيراد ملف هوية", "", "ملف هوية (*.json)")
        if not path:
            return
        try:
            self.set_data(branding.import_file(path))
        except Exception as e:                        # noqa: BLE001
            err(self, e)
            return
        info(self, "حُمّلت الهوية من الملف — راجع المعاينة ثم اضغط "
                   "«اعتماد الهوية».")


def open_dialog(parent=None, user=None):
    dlg = FactoryIdentityDialog(parent, user)
    dlg.exec_()
    return dlg
