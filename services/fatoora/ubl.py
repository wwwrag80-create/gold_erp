# -*- coding: utf-8 -*-
"""مستند الفاتورة الإلكترونية — UBL 2.1 بمواصفات الهيئة، وختمه ورمزه.

**مراحل الإصدار** (دليل المواصفات الفنية + معايير الأمان):
  1) يُبنى المستند: البائع · المشتري · الأسطر · الضريبة · الإجماليات ·
     العدّاد (ICV) · بصمة المستند السابق (PIH) · المرجع للأصل (للإشعارات).
  2) **البصمة**: يُحذف منه التوقيع والامتدادات ورمز QR — مع إبقاء
     الفراغات المحيطة بها كما هي — ثم يُوحَّد (C14N) ويُحسب SHA-256.
  3) **الختم**: توقيع ECDSA على البصمة بمفتاح الجهاز، ثم خصائص XAdES
     الموقّعة (زمن التوقيع · بصمة الشهادة · مُصدِرها · رقمها).
  4) **رمز QR** بتسعة حقول: البائع · الرقم الضريبي · الزمن · الإجمالي ·
     الضريبة · البصمة · التوقيع · المفتاح العام · توقيع الشهادة.

**لماذا نصٌّ مولَّد لا مكتبة XML**: الهيئة تعيد حساب البصمة من النص
نفسه، وأي فرقٍ في فراغٍ أو ترتيب سماتٍ يُسقط الفاتورة. المولِّد هنا
يكتب المستند بصيغته القانونية (C14N) مباشرةً: سماتٌ مرتّبة، عناصر
فارغة بوسمَي فتحٍ وإغلاق، وتهريبٌ موحّد — فالبصمة المحسوبة محليّاً هي
ما تحسبه الهيئة حرفاً بحرف. ومقطع التوقيع منسوخٌ حرفياً من الصيغة
التي تقبلها منصّة فاتورة.
"""
import base64
import hashlib
import uuid as _uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from services.fatoora import ec

# بصمة «المستند السابق» لأول مستندٍ في السلسلة — ثابتٌ تنشره الهيئة
FIRST_PIH = ("NWZlY2ViNjZmZmM4NmYzOGQ5NTI3ODZjNmQ2OTZjNzljMmRiYzIzOWRk"
             "NGU5MWI0NjcyOWQ3M2EyN2ZiNTdlOQ==")

ROOT_OPEN = (
    '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"'
    ' xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:'
    'CommonAggregateComponents-2"'
    ' xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:'
    'CommonBasicComponents-2"'
    ' xmlns:ext="urn:oasis:names:specification:ubl:schema:xsd:'
    'CommonExtensionComponents-2">')
XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>\n'

TYPE_CODES = {"invoice": "388", "credit": "381", "debit": "383"}
SUBTYPES = {"standard": "0100000", "simplified": "0200000"}

# ── مقطع التوقيع (UBLExtensions) — حرفياً بالصيغة المقبولة ──
SIG_BLOCK = """    <ext:UBLExtensions>
        <ext:UBLExtension>
            <ext:ExtensionURI>urn:oasis:names:specification:ubl:dsig:enveloped:xades</ext:ExtensionURI>
            <ext:ExtensionContent>
                <sig:UBLDocumentSignatures xmlns:sac="urn:oasis:names:specification:ubl:schema:xsd:SignatureAggregateComponents-2" xmlns:sbc="urn:oasis:names:specification:ubl:schema:xsd:SignatureBasicComponents-2" xmlns:sig="urn:oasis:names:specification:ubl:schema:xsd:CommonSignatureComponents-2">
                    <sac:SignatureInformation>
                        <cbc:ID>urn:oasis:names:specification:ubl:signature:1</cbc:ID>
                        <sbc:ReferencedSignatureID>urn:oasis:names:specification:ubl:signature:Invoice</sbc:ReferencedSignatureID>
                        <ds:Signature Id="signature" xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
                            <ds:SignedInfo>
                                <ds:CanonicalizationMethod Algorithm="http://www.w3.org/2006/12/xml-c14n11"></ds:CanonicalizationMethod>
                                <ds:SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#ecdsa-sha256"></ds:SignatureMethod>
                                <ds:Reference Id="invoiceSignedData" URI="">
                                    <ds:Transforms>
                                        <ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116">
                                            <ds:XPath>not(//ancestor-or-self::ext:UBLExtensions)</ds:XPath>
                                        </ds:Transform>
                                        <ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116">
                                            <ds:XPath>not(//ancestor-or-self::cac:Signature)</ds:XPath>
                                        </ds:Transform>
                                        <ds:Transform Algorithm="http://www.w3.org/TR/1999/REC-xpath-19991116">
                                            <ds:XPath>not(//ancestor-or-self::cac:AdditionalDocumentReference[cbc:ID='QR'])</ds:XPath>
                                        </ds:Transform>
                                        <ds:Transform Algorithm="http://www.w3.org/2006/12/xml-c14n11"></ds:Transform>
                                    </ds:Transforms>
                                    <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>
                                    <ds:DigestValue>{invoice_hash}</ds:DigestValue>
                                </ds:Reference>
                                <ds:Reference Type="http://www.w3.org/2000/09/xmldsig#SignatureProperties" URI="#xadesSignedProperties">
                                    <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>
                                    <ds:DigestValue>{props_hash}</ds:DigestValue>
                                </ds:Reference>
                            </ds:SignedInfo>
                            <ds:SignatureValue>{signature}</ds:SignatureValue>
                            <ds:KeyInfo>
                                <ds:X509Data>
                                    <ds:X509Certificate>{certificate}</ds:X509Certificate>
                                </ds:X509Data>
                            </ds:KeyInfo>
                            <ds:Object>
                            <xades:QualifyingProperties Target="signature" xmlns:xades="http://uri.etsi.org/01903/v1.3.2#">
                                <xades:SignedProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#" Id="xadesSignedProperties">
                                    <xades:SignedSignatureProperties>
                                        <xades:SigningTime>{signing_time}</xades:SigningTime>
                                        <xades:SigningCertificate>
                                            <xades:Cert>
                                                <xades:CertDigest>
                                                    <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>
                                                    <ds:DigestValue>{cert_hash}</ds:DigestValue>
                                                </xades:CertDigest>
                                                <xades:IssuerSerial>
                                                    <ds:X509IssuerName>{issuer}</ds:X509IssuerName>
                                                    <ds:X509SerialNumber>{serial}</ds:X509SerialNumber>
                                                </xades:IssuerSerial>
                                            </xades:Cert>
                                        </xades:SigningCertificate>
                                    </xades:SignedSignatureProperties>
                                </xades:SignedProperties>
                            </xades:QualifyingProperties>
                            </ds:Object>
                        </ds:Signature>
                    </sac:SignatureInformation>
                </sig:UBLDocumentSignatures>
            </ext:ExtensionContent>
        </ext:UBLExtension>
    </ext:UBLExtensions>"""

# ── الخصائص الموقّعة كما تُبصَم (نصٌّ بعينه تعيد الهيئة بناءه) ──
SIGNED_PROPS_FOR_HASH = (
    '<xades:SignedProperties xmlns:xades="http://uri.etsi.org/01903/v1.3.2#"'
    ' Id="xadesSignedProperties">\n'
    '                                    <xades:SignedSignatureProperties>\n'
    '                                        <xades:SigningTime>{signing_time}'
    '</xades:SigningTime>\n'
    '                                        <xades:SigningCertificate>\n'
    '                                            <xades:Cert>\n'
    '                                                <xades:CertDigest>\n'
    '                                                    <ds:DigestMethod'
    ' xmlns:ds="http://www.w3.org/2000/09/xmldsig#"'
    ' Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>\n'
    '                                                    <ds:DigestValue'
    ' xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{cert_hash}'
    '</ds:DigestValue>\n'
    '                                                </xades:CertDigest>\n'
    '                                                <xades:IssuerSerial>\n'
    '                                                    <ds:X509IssuerName'
    ' xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{issuer}'
    '</ds:X509IssuerName>\n'
    '                                                    <ds:X509SerialNumber'
    ' xmlns:ds="http://www.w3.org/2000/09/xmldsig#">{serial}'
    '</ds:X509SerialNumber>\n'
    '                                                </xades:IssuerSerial>\n'
    '                                            </xades:Cert>\n'
    '                                        </xades:SigningCertificate>\n'
    '                                    </xades:SignedSignatureProperties>\n'
    '                                </xades:SignedProperties>')


# ══════════════════════════ الأرقام ══════════════════════════
def money(v):
    """مبلغٌ بخانتين عشريتين وتقريبٍ «نصف لأعلى» — كما تحسبه الهيئة."""
    return Decimal(str(v or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def fmt(v):
    return f"{money(v):.2f}"


# ══════════════════════════ المولِّد ══════════════════════════
def _esc_text(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\r", "&#xD;"))


def _esc_attr(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace('"', "&quot;").replace("\t", "&#x9;")
            .replace("\n", "&#xA;").replace("\r", "&#xD;"))


class E:
    """عنصرٌ بسيط: وسم · نص · سمات · أبناء — يُكتب بصيغة C14N مباشرةً."""
    __slots__ = ("tag", "text", "attrs", "kids")

    def __init__(self, tag, text=None, attrs=None, kids=None):
        self.tag, self.text = tag, text
        self.attrs = attrs or {}
        self.kids = [k for k in (kids or []) if k is not None]

    def render(self, level):
        pad = "    " * level
        # السمات بلا بادئة تُرتَّب أبجدياً — قاعدة C14N
        at = "".join(f' {k}="{_esc_attr(v)}"'
                     for k, v in sorted(self.attrs.items()))
        if self.kids:
            inner = "\n".join(k.render(level + 1) for k in self.kids)
            return f"{pad}<{self.tag}{at}>\n{inner}\n{pad}</{self.tag}>"
        txt = "" if self.text is None else _esc_text(self.text)
        return f"{pad}<{self.tag}{at}>{txt}</{self.tag}>"


def _party_address(a):
    kids = [E("cbc:StreetName", a.get("street"))]
    if a.get("additional_street"):
        kids.append(E("cbc:AdditionalStreetName", a.get("additional_street")))
    kids.append(E("cbc:BuildingNumber", a.get("building")))
    if a.get("plot"):
        kids.append(E("cbc:PlotIdentification", a.get("plot")))
    kids += [E("cbc:CitySubdivisionName", a.get("district")),
             E("cbc:CityName", a.get("city")),
             E("cbc:PostalZone", a.get("postal")),
             E("cac:Country", kids=[E("cbc:IdentificationCode", "SA")])]
    return E("cac:PostalAddress", kids=kids)


def _tax_category(tag, pct):
    return E(tag, kids=[
        E("cbc:ID", "S", {"schemeAgencyID": "6", "schemeID": "UN/ECE 5305"})
        if tag == "cac:TaxCategory" else E("cbc:ID", "S"),
        E("cbc:Percent", f"{pct:.2f}"),
        E("cac:TaxScheme", kids=[
            E("cbc:ID", "VAT", {"schemeAgencyID": "6",
                                "schemeID": "UN/ECE 5153"})
            if tag == "cac:TaxCategory" else E("cbc:ID", "VAT")])])


def totals(lines, rate=15.0):
    """إجماليات المستند من أسطره — بالقواعد نفسها التي تتحقّق بها الهيئة."""
    net = sum((money(li["amount"]) for li in lines), Decimal("0"))
    vat = money(net * Decimal(str(rate)) / Decimal("100"))
    return {"net": net, "vat": vat, "gross": net + vat}


def build_body(doc):
    """عناصر المستند بعد مقطع التوقيع — قائمة (عنصر, قابلٌ للحذف عند البصم)."""
    seller, buyer = doc["seller"], doc["buyer"]
    rate = float(doc.get("rate", 15.0))
    t = totals(doc["lines"], rate)
    type_code = TYPE_CODES[doc["kind"]]
    std = doc["subtype"] == "standard"
    items = [
        E("cbc:ProfileID", "reporting:1.0"),
        E("cbc:ID", doc["number"]),
        E("cbc:UUID", doc["uuid"]),
        E("cbc:IssueDate", doc["issue_date"]),
        E("cbc:IssueTime", doc["issue_time"]),
        E("cbc:InvoiceTypeCode", type_code, {"name": SUBTYPES[doc["subtype"]]}),
    ]
    if doc.get("note"):
        items.append(E("cbc:Note", doc["note"], {"languageID": "ar"}))
    items += [E("cbc:DocumentCurrencyCode", "SAR"),
              E("cbc:TaxCurrencyCode", "SAR")]
    for ref in doc.get("billing_refs") or []:
        items.append(E("cac:BillingReference", kids=[
            E("cac:InvoiceDocumentReference", kids=[E("cbc:ID", ref)])]))
    items += [
        E("cac:AdditionalDocumentReference", kids=[
            E("cbc:ID", "ICV"), E("cbc:UUID", str(int(doc["icv"])))]),
        E("cac:AdditionalDocumentReference", kids=[
            E("cbc:ID", "PIH"),
            E("cac:Attachment", kids=[E("cbc:EmbeddedDocumentBinaryObject",
                                        doc["pih"], {"mimeCode": "text/plain"})])]),
    ]
    qr = E("cac:AdditionalDocumentReference", kids=[
        E("cbc:ID", "QR"),
        E("cac:Attachment", kids=[E("cbc:EmbeddedDocumentBinaryObject",
                                    doc.get("qr", ""),
                                    {"mimeCode": "text/plain"})])])
    sig = E("cac:Signature", kids=[
        E("cbc:ID", "urn:oasis:names:specification:ubl:signature:Invoice"),
        E("cbc:SignatureMethod",
          "urn:oasis:names:specification:ubl:dsig:enveloped:xades")])
    supplier = E("cac:AccountingSupplierParty", kids=[E("cac:Party", kids=[
        E("cac:PartyIdentification", kids=[
            E("cbc:ID", seller["crn"], {"schemeID": seller.get("crn_scheme")
                                        or "CRN"})]),
        _party_address(seller),
        E("cac:PartyTaxScheme", kids=[
            E("cbc:CompanyID", seller["vat"]),
            E("cac:TaxScheme", kids=[E("cbc:ID", "VAT")])]),
        E("cac:PartyLegalEntity", kids=[
            E("cbc:RegistrationName", seller["name"])]),
    ])])
    bkids = []
    if buyer.get("crn"):
        bkids.append(E("cac:PartyIdentification", kids=[
            E("cbc:ID", buyer["crn"], {"schemeID": "CRN"})]))
    if std or buyer.get("street"):
        bkids.append(_party_address(buyer))
    if buyer.get("vat"):
        bkids.append(E("cac:PartyTaxScheme", kids=[
            E("cbc:CompanyID", buyer["vat"]),
            E("cac:TaxScheme", kids=[E("cbc:ID", "VAT")])]))
    if buyer.get("name"):
        bkids.append(E("cac:PartyLegalEntity", kids=[
            E("cbc:RegistrationName", buyer["name"])]))
    customer = E("cac:AccountingCustomerParty",
                  kids=[E("cac:Party", kids=bkids)] if bkids else None)
    delivery = E("cac:Delivery", kids=[
        E("cbc:ActualDeliveryDate", doc.get("supply_date")
          or doc["issue_date"])])
    pm_kids = [E("cbc:PaymentMeansCode", doc.get("payment_means") or "30")]
    if doc["kind"] in ("credit", "debit"):
        # سبب الإشعار (KSA-10) — إلزاميٌّ لكل إشعارٍ دائنٍ أو مدين
        pm_kids.append(E("cbc:InstructionNote", doc.get("reason")
                         or "تعديل الفاتورة"))
    payment = E("cac:PaymentMeans", kids=pm_kids)
    tax_full = E("cac:TaxTotal", kids=[
        E("cbc:TaxAmount", f"{t['vat']:.2f}", {"currencyID": "SAR"}),
        E("cac:TaxSubtotal", kids=[
            E("cbc:TaxableAmount", f"{t['net']:.2f}", {"currencyID": "SAR"}),
            E("cbc:TaxAmount", f"{t['vat']:.2f}", {"currencyID": "SAR"}),
            _tax_category("cac:TaxCategory", rate)])])
    tax_only = E("cac:TaxTotal", kids=[
        E("cbc:TaxAmount", f"{t['vat']:.2f}", {"currencyID": "SAR"})])
    legal = E("cac:LegalMonetaryTotal", kids=[
        E("cbc:LineExtensionAmount", f"{t['net']:.2f}", {"currencyID": "SAR"}),
        E("cbc:TaxExclusiveAmount", f"{t['net']:.2f}", {"currencyID": "SAR"}),
        E("cbc:TaxInclusiveAmount", f"{t['gross']:.2f}", {"currencyID": "SAR"}),
        E("cbc:AllowanceTotalAmount", "0.00", {"currencyID": "SAR"}),
        E("cbc:PrepaidAmount", "0.00", {"currencyID": "SAR"}),
        E("cbc:PayableAmount", f"{t['gross']:.2f}", {"currencyID": "SAR"})])
    body = [(el, False) for el in items]
    body += [(qr, True), (sig, True), (supplier, False), (customer, False),
             (delivery, False), (payment, False), (tax_full, False),
             (tax_only, False), (legal, False)]
    for i, li in enumerate(doc["lines"], 1):
        amt = money(li["amount"])
        lvat = money(amt * Decimal(str(rate)) / Decimal("100"))
        body.append((E("cac:InvoiceLine", kids=[
            E("cbc:ID", str(i)),
            E("cbc:InvoicedQuantity", "1.000000", {"unitCode": "PCE"}),
            E("cbc:LineExtensionAmount", f"{amt:.2f}", {"currencyID": "SAR"}),
            E("cac:TaxTotal", kids=[
                E("cbc:TaxAmount", f"{lvat:.2f}", {"currencyID": "SAR"}),
                E("cbc:RoundingAmount", f"{amt + lvat:.2f}",
                  {"currencyID": "SAR"})]),
            E("cac:Item", kids=[E("cbc:Name", li["name"]),
                                _tax_category("cac:ClassifiedTaxCategory",
                                              rate)]),
            E("cac:Price", kids=[E("cbc:PriceAmount", f"{amt:.2f}",
                                   {"currencyID": "SAR"})]),
        ]), False))
    return body, t


def _assemble(body, sig_block, pure=False):
    """النص الكامل — أو «النقي» للبصم (بلا ما يُحذف، والفراغات باقية)."""
    parts = [ROOT_OPEN, "\n    ", "" if pure else sig_block.lstrip(" ")]
    for el, removable in body:
        parts.append("\n    ")
        if not (pure and removable):
            parts.append(el.render(1).lstrip(" "))
    parts.append("\n</Invoice>")
    return ("" if pure else XML_DECL) + "".join(parts)


def invoice_hash(body):
    canon = _assemble(body, "", pure=True).encode("utf-8")
    return base64.b64encode(hashlib.sha256(canon).digest()).decode("ascii")


def hash_of_xml(xml_text):
    """يعيد حساب بصمة مستندٍ محفوظ من نصّه — للتحقق من سلامته لاحقاً."""
    s = xml_text
    if s.startswith("<?xml"):
        s = s[s.index("?>") + 2:].lstrip("\n")
    s = _cut(s, "<ext:UBLExtensions>", "</ext:UBLExtensions>")
    s = _cut(s, "<cac:Signature>", "</cac:Signature>")
    qr_at = s.find("<cbc:ID>QR</cbc:ID>")
    if qr_at >= 0:
        start = s.rfind("<cac:AdditionalDocumentReference>", 0, qr_at)
        end = s.index("</cac:AdditionalDocumentReference>", qr_at) + len(
            "</cac:AdditionalDocumentReference>")
        s = s[:start] + s[end:]
    return base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()
                            ).decode("ascii")


def _cut(s, open_tag, close_tag):
    a = s.find(open_tag)
    if a < 0:
        return s
    b = s.index(close_tag, a) + len(close_tag)
    return s[:a] + s[b:]


# ══════════════════════════ رمز QR (TLV) ══════════════════════════
def tlv(tag, value):
    b = value if isinstance(value, (bytes, bytearray)) else \
        str(value).encode("utf-8")
    if len(b) > 255:
        raise ValueError(f"حقل QR رقم {tag} أطول من المسموح")
    return bytes([tag, len(b)]) + bytes(b)


def build_qr(doc, t, inv_hash, signature_b64, cert):
    ts = f"{doc['issue_date']}T{doc['issue_time']}Z"
    data = (tlv(1, doc["seller"]["name"]) + tlv(2, doc["seller"]["vat"])
            + tlv(3, ts) + tlv(4, f"{t['gross']:.2f}")
            + tlv(5, f"{t['vat']:.2f}") + tlv(6, inv_hash)
            + tlv(7, signature_b64) + tlv(8, cert.spki))
    if doc["subtype"] == "simplified":
        data += tlv(9, cert.signature)      # توقيع الهيئة على الشهادة
    return base64.b64encode(data).decode("ascii")


def parse_qr(b64):
    raw = base64.b64decode(b64)
    out, i = {}, 0
    while i < len(raw):
        tag, ln = raw[i], raw[i + 1]
        out[tag] = raw[i + 2:i + 2 + ln]
        i += 2 + ln
    return out


# ══════════════════════════ الإصدار الكامل ══════════════════════════
def cert_hash(cert_b64):
    return base64.b64encode(hashlib.sha256(
        cert_b64.encode("ascii")).hexdigest().encode("ascii")).decode("ascii")


def sign_document(doc, key, cert_b64, signing_time=None):
    """يبني المستند ويبصمه ويختمه — يعيد dict بالنص والبصمة والرمز.

    `cert_b64`: شهادة الهيئة كما تُفكّ من binarySecurityToken (DER base64).
    """
    doc = dict(doc)
    doc.setdefault("uuid", str(_uuid.uuid4()))
    cert = ec.Certificate.from_b64(cert_b64)
    body, t = build_body(doc)
    inv_hash = invoice_hash(body)
    signature = base64.b64encode(
        key.sign(base64.b64decode(inv_hash))).decode("ascii")
    st = signing_time or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    chash = cert_hash("".join(cert_b64.split()))
    props = {"signing_time": st, "cert_hash": chash,
             "issuer": _esc_text(cert.issuer_string()),
             "serial": str(cert.serial)}
    props_for_hash = SIGNED_PROPS_FOR_HASH.format(**props)
    props_hash = base64.b64encode(hashlib.sha256(
        props_for_hash.encode("utf-8")).hexdigest().encode("ascii")
    ).decode("ascii")
    qr = build_qr(doc, t, inv_hash, signature, cert)
    doc["qr"] = qr
    body, t = build_body(doc)                   # الرمز لا يمسّ البصمة
    block = SIG_BLOCK.format(invoice_hash=inv_hash, props_hash=props_hash,
                             signature=signature,
                             certificate="".join(cert_b64.split()),
                             **props)
    xml = _assemble(body, block)
    return {"xml": xml, "hash": inv_hash, "qr": qr, "uuid": doc["uuid"],
            "signature": signature, "totals": t, "signing_time": st}


def verify_document(xml_text, cert_b64=None):
    """فحصٌ مستقل لمستندٍ محفوظ: بصمته تطابق نصّه، وتوقيعه صحيح."""
    import re
    h = hash_of_xml(xml_text)
    m = re.search(r'<ds:Reference Id="invoiceSignedData" URI="">.*?'
                  r"<ds:DigestValue>([^<]+)</ds:DigestValue>", xml_text, re.S)
    stored = m.group(1) if m else ""
    sm = re.search(r"<ds:SignatureValue>([^<]+)</ds:SignatureValue>",
                   xml_text)
    cm = re.search(r"<ds:X509Certificate>([^<]+)</ds:X509Certificate>",
                   xml_text)
    sig_ok = False
    if sm and (cm or cert_b64):
        try:
            cert = ec.Certificate.from_b64(cert_b64 or cm.group(1))
            sig_ok = ec.verify(cert.public_point, base64.b64decode(h),
                               base64.b64decode(sm.group(1)))
        except Exception:
            sig_ok = False
    return {"hash": h, "hash_ok": h == stored, "signature_ok": sig_ok}
