# -*- coding: utf-8 -*-
"""تشفير الختم الإلكتروني — secp256k1 وASN.1 بلا أي مكتبة خارجية.

**لماذا بلا مكتبة**: الملف التنفيذي يُبنى بـPyQt5 وحده (MAKE_EXE.bat)،
ومكتبة `cryptography` تحمل أجزاءً مترجمة تختلف من جهازٍ لجهاز وقد
تغيب فلا يعمل الختم أصلاً. والمطلوب هنا محدودٌ ومعرَّف تماماً:
  · منحنى secp256k1 (المعتمد في مواصفات الهيئة للختم التشفيري)
  · توقيع ECDSA-SHA256 بـ«k» حتميّ وفق RFC 6979 — لا يعتمد على جودة
    مولّد العشوائية في الجهاز، والتوقيع نفسه يُعاد إنتاجه للمراجعة
  · ترميز DER للمفتاح وطلب الشهادة (PKCS#10) وقراءة الشهادة (X.509)

كل دالةٍ هنا مُختبرةٌ بمقابلٍ مستقل (openssl) — انظر tools/smoke_flow.
"""
import base64
import hashlib
import hmac
import secrets

# ══════════════════════════ secp256k1 ══════════════════════════
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

OID_EC_PUBLIC_KEY = "1.2.840.10045.2.1"
OID_SECP256K1 = "1.3.132.0.10"
OID_ECDSA_SHA256 = "1.2.840.10045.4.3.2"


def _inv(a, m=P):
    return pow(a, m - 2, m)


def _jadd(p1, p2):
    """جمع نقطتين بالإحداثيات اليعقوبية (أسرع من الأفينية بكثير)."""
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1, z1 = p1
    x2, y2, z2 = p2
    z1s, z2s = z1 * z1 % P, z2 * z2 % P
    u1, u2 = x1 * z2s % P, x2 * z1s % P
    s1, s2 = y1 * z2s * z2 % P, y2 * z1s * z1 % P
    if u1 == u2:
        if s1 != s2:
            return None
        return _jdbl(p1)
    h, r = (u2 - u1) % P, (s2 - s1) % P
    h2 = h * h % P
    h3 = h * h2 % P
    u1h2 = u1 * h2 % P
    x3 = (r * r - h3 - 2 * u1h2) % P
    y3 = (r * (u1h2 - x3) - s1 * h3) % P
    return (x3, y3, h * z1 * z2 % P)


def _jdbl(p1):
    if p1 is None:
        return None
    x, y, z = p1
    if y == 0:
        return None
    ysq = y * y % P
    s = 4 * x * ysq % P
    m = 3 * x * x % P                      # a = 0 على هذا المنحنى
    x3 = (m * m - 2 * s) % P
    y3 = (m * (s - x3) - 8 * ysq * ysq) % P
    return (x3, y3, 2 * y * z % P)


def _affine(p1):
    if p1 is None:
        return None
    x, y, z = p1
    zi = _inv(z)
    zi2 = zi * zi % P
    return (x * zi2 % P, y * zi2 * zi % P)


def _mul(k, point=(GX, GY)):
    acc = None
    add = (point[0], point[1], 1)
    while k:
        if k & 1:
            acc = _jadd(acc, add)
        add = _jdbl(add)
        k >>= 1
    return _affine(acc)


def _on_curve(pt):
    x, y = pt
    return (y * y - x * x * x - 7) % P == 0


# ══════════════════════════ ECDSA ══════════════════════════
def _rfc6979_k(d, h1):
    """«k» حتميّ من المفتاح والبصمة (RFC 6979 §3.2) — بلا عشوائية."""
    x = d.to_bytes(32, "big")
    h = (int.from_bytes(h1, "big") % N).to_bytes(32, "big")
    v, k = b"\x01" * 32, b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + h, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        cand = int.from_bytes(v, "big")
        if 1 <= cand < N:
            return cand
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign(d, message):
    """توقيع ECDSA-SHA256 على `message` (بايتات) — يعيد DER."""
    h1 = hashlib.sha256(message).digest()
    e = int.from_bytes(h1, "big")
    while True:
        k = _rfc6979_k(d, h1)
        r = _mul(k)[0] % N
        s = _inv(k, N) * (e + r * d) % N
        if r and s:
            break
        h1 = hashlib.sha256(h1).digest()        # لا يحدث عملياً
    if s > N // 2:                              # الصيغة «المنخفضة» المعتادة
        s = N - s
    return der_seq(der_int(r), der_int(s))


def verify(pub, message, sig_der):
    """يتحقّق من توقيع DER على `message` بالمفتاح العام (x, y)."""
    try:
        seq = parse(sig_der)[0]
        r, s = (int.from_bytes(c.value, "big") for c in seq.children)
    except Exception:
        return False
    if not (1 <= r < N and 1 <= s < N):
        return False
    e = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = _inv(s, N)
    p1 = _mul(e * w % N)
    p2 = _mul(r * w % N, pub)
    j = _jadd((p1[0], p1[1], 1) if p1 else None,
              (p2[0], p2[1], 1) if p2 else None)
    pt = _affine(j)
    return pt is not None and pt[0] % N == r


class PrivateKey:
    """مفتاح الجهاز الخاص — يُولَّد مرةً ويُحفظ على هذا الجهاز وحده."""

    def __init__(self, d):
        if not 1 <= d < N:
            raise ValueError("مفتاح خاص غير صالح")
        self.d = d
        self.pub = _mul(d)

    @classmethod
    def generate(cls):
        return cls(secrets.randbelow(N - 1) + 1)

    def sign(self, message):
        return sign(self.d, message)

    # ── الترميز ──
    def public_point(self):
        x, y = self.pub
        return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")

    def spki_der(self):
        return spki_der(self.public_point())

    def to_pem(self):
        """صيغة SEC1 «EC PRIVATE KEY» — التي تقرؤها openssl وأدوات الهيئة."""
        der = der_seq(
            der_int(1),
            der_octets(self.d.to_bytes(32, "big")),
            der_ctx(0, der_oid(OID_SECP256K1)),
            der_ctx(1, der_bits(self.public_point())))
        return _pem("EC PRIVATE KEY", der)

    @classmethod
    def from_pem(cls, pem):
        der = _unpem(pem)
        node = parse(der)[0]
        kids = node.children
        if kids and kids[0].tag == 0x02 and len(kids) >= 2 and \
                kids[1].tag == 0x04:                           # SEC1
            return cls(int.from_bytes(kids[1].value, "big"))
        # PKCS#8: SEQUENCE{INT 0, AlgId, OCTET STRING(SEC1)}
        inner = parse(kids[2].value)[0]
        return cls(int.from_bytes(inner.children[1].value, "big"))


def spki_der(point):
    return der_seq(der_seq(der_oid(OID_EC_PUBLIC_KEY), der_oid(OID_SECP256K1)),
                   der_bits(point))


def point_from_spki(der):
    node = parse(der)[0]
    raw = node.children[1].value[1:]                           # بعد بايت «0»
    if raw[0] != 4 or len(raw) != 65:
        raise ValueError("مفتاح عام غير مدعوم")
    return (int.from_bytes(raw[1:33], "big"), int.from_bytes(raw[33:], "big"))


# ══════════════════════════ DER ══════════════════════════
def _len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def der_tlv(tag, value):
    return bytes([tag]) + _len(len(value)) + value


def der_int(v):
    b = v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big")
    return der_tlv(0x02, b)


def der_seq(*parts):
    return der_tlv(0x30, b"".join(parts))


def der_set(*parts):
    # SET OF يُرتَّب بترميزه (DER) — عناصرنا هنا واحدٌ في كل مجموعة
    return der_tlv(0x31, b"".join(sorted(parts)))


def der_octets(b):
    return der_tlv(0x04, b)


def der_bits(b):
    return der_tlv(0x03, b"\x00" + b)


def der_utf8(s):
    return der_tlv(0x0C, str(s).encode("utf-8"))


def der_printable(s):
    return der_tlv(0x13, str(s).encode("ascii"))


def der_ctx(n, inner, constructed=True):
    return der_tlv((0xA0 if constructed else 0x80) | n, inner)


def der_oid(dotted):
    parts = [int(x) for x in dotted.split(".")]
    out = bytearray([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        chunk = [p & 0x7F]
        p >>= 7
        while p:
            chunk.append(0x80 | (p & 0x7F))
            p >>= 7
        out.extend(reversed(chunk))
    return der_tlv(0x06, bytes(out))


class Node:
    __slots__ = ("tag", "value", "raw", "children")

    def __init__(self, tag, value, raw):
        self.tag, self.value, self.raw = tag, value, raw
        self.children = parse(value) if tag & 0x20 else []


def parse(data):
    """يفكّ ترميز DER إلى عُقَد (tag · value · raw · children)."""
    out, i = [], 0
    while i < len(data):
        tag = data[i]
        ln = data[i + 1]
        j = i + 2
        if ln & 0x80:
            nb = ln & 0x7F
            ln = int.from_bytes(data[j:j + nb], "big")
            j += nb
        out.append(Node(tag, data[j:j + ln], data[i:j + ln]))
        i = j + ln
    return out


def oid_str(value):
    first = value[0]
    parts = [first // 40, first % 40]
    acc = 0
    for b in value[1:]:
        acc = (acc << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(acc)
            acc = 0
    return ".".join(str(p) for p in parts)


def _pem(label, der):
    b = base64.b64encode(der).decode("ascii")
    lines = "\n".join(b[i:i + 64] for i in range(0, len(b), 64))
    return f"-----BEGIN {label}-----\n{lines}\n-----END {label}-----\n"


def _unpem(pem):
    lines = [ln.strip() for ln in str(pem).strip().splitlines()
             if ln.strip() and not ln.startswith("-----")]
    return base64.b64decode("".join(lines))


# ══════════════════════════ الأسماء (X.500) ══════════════════════════
NAME_OIDS = {
    "C": "2.5.4.6", "O": "2.5.4.10", "OU": "2.5.4.11", "CN": "2.5.4.3",
    "SN": "2.5.4.4", "UID": "0.9.2342.19200300.100.1.1",
    "title": "2.5.4.12", "registeredAddress": "2.5.4.26",
    "businessCategory": "2.5.4.15", "DC": "0.9.2342.19200300.100.1.25",
    "L": "2.5.4.7", "ST": "2.5.4.8", "emailAddress": "1.2.840.113549.1.9.1",
}
_OID_NAMES = {v: k for k, v in NAME_OIDS.items()}


def der_name(pairs):
    """اسمٌ مميّز: [(«C», «SA»), («CN», …)] — الدولة PrintableString
    وكل ما عداها UTF8String كما تُنشئه openssl بإعداد الهيئة."""
    rdns = []
    for key, val in pairs:
        enc = der_printable(val) if key == "C" else der_utf8(val)
        rdns.append(der_set(der_seq(der_oid(NAME_OIDS[key]), enc)))
    return der_seq(*rdns)


def name_pairs(node):
    out = []
    for rdn in node.children:
        for atv in rdn.children:
            oid = oid_str(atv.children[0].value)
            val = atv.children[1].value.decode("utf-8", "replace")
            out.append((_OID_NAMES.get(oid, oid), val))
    return out


# ══════════════════════════ طلب الشهادة (CSR) ══════════════════════════
TEMPLATE_BY_ENV = {
    "sandbox": "TSTZATCA-Code-Signing",
    "simulation": "PREZATCA-Code-Signing",
    "production": "ZATCA-Code-Signing",
}


def build_csr(key, *, common_name, org, org_unit, vat_number, egs_serial,
              invoice_types, address, category, env):
    """طلب شهادةٍ بمواصفات الهيئة بالضبط (دليل الربط — CSR):

      Subject: C=SA · OU=الفرع · O=المنشأة · CN=اسم الجهاز
      امتداد قالب الشهادة 1.3.6.1.4.1.311.20.2 = …ZATCA-Code-Signing
      SAN (dirName): SN=1-النظام|2-الطراز|3-الرقم · UID=الرقم الضريبي ·
                     title=أنواع الفواتير (1100) · registeredAddress ·
                     businessCategory
    """
    subject = der_name([("C", "SA"), ("OU", org_unit), ("O", org),
                        ("CN", common_name)])
    template = TEMPLATE_BY_ENV.get(env, TEMPLATE_BY_ENV["production"])
    ext_template = der_seq(der_oid("1.3.6.1.4.1.311.20.2"),
                           der_octets(der_printable(template)))
    dir_name = der_name([("SN", egs_serial), ("UID", vat_number),
                         ("title", invoice_types),
                         ("registeredAddress", address),
                         ("businessCategory", category)])
    san = der_seq(der_ctx(4, dir_name))                  # [4] directoryName
    ext_san = der_seq(der_oid("2.5.29.17"), der_octets(san))
    attrs = der_ctx(0, der_seq(
        der_oid("1.2.840.113549.1.9.14"),                # extensionRequest
        der_set(der_seq(ext_template, ext_san))))
    info = der_seq(der_int(0), subject, key.spki_der(), attrs)
    sig = key.sign(info)
    csr = der_seq(info, der_seq(der_oid(OID_ECDSA_SHA256)), der_bits(sig))
    return _pem("CERTIFICATE REQUEST", csr)


# ══════════════════════════ الشهادة (X.509) ══════════════════════════
class Certificate:
    """ما يلزم الختمَ من شهادة الهيئة: المُصدِر والرقم التسلسلي والمفتاح
    العام وتوقيع الجهة المُصدِرة والصلاحية."""

    def __init__(self, der):
        self.der = der
        cert = parse(der)[0]
        tbs, _alg, sigbits = cert.children[:3]
        kids = tbs.children
        i = 1 if kids[0].tag == 0xA0 else 0              # [0] version
        self.serial = int.from_bytes(kids[i].value, "big")
        self.issuer = name_pairs(kids[i + 2])
        validity = kids[i + 3].children
        self.not_before = _time(validity[0])
        self.not_after = _time(validity[1])
        self.subject = name_pairs(kids[i + 4])
        self.spki = kids[i + 5].raw
        self.public_point = point_from_spki(self.spki)
        self.signature = sigbits.value[1:]               # بعد بايت «0»

    @classmethod
    def from_b64(cls, text):
        """من نص base64 (DER) أو PEM — كلاهما مقبول."""
        t = str(text or "").strip()
        if "BEGIN" in t:
            return cls(_unpem(t))
        return cls(base64.b64decode("".join(t.split())))

    def issuer_string(self):
        """«CN=…, DC=…, DC=…» — بالترتيب المعكوس كما تكتبه الهيئة."""
        return ", ".join(f"{k}={v}" for k, v in reversed(self.issuer))

    def subject_cn(self):
        for k, v in self.subject:
            if k == "CN":
                return v
        return ""


def _time(node):
    s = node.value.decode("ascii")
    if node.tag == 0x17:                                 # UTCTime
        yy = int(s[:2])
        s = ("19" if yy >= 50 else "20") + s
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}:{s[12:14]}"


def self_signed_certificate(key, common_name="EGS-SELFTEST", days=365):
    """شهادةٌ ذاتية التوقيع — **للفحص الذاتي وحده** (لا تُقبل لدى الهيئة).

    بها يختبر النظام دورة الختم كاملةً بلا إنترنت: بصمة · توقيع ·
    رمز QR · تحقّق — قبل أن تُطلب الشهادة الحقيقية من البوابة.
    """
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    t0 = now.strftime("%y%m%d%H%M%SZ").encode("ascii")
    t1 = (now + timedelta(days=days)).strftime("%y%m%d%H%M%SZ").encode("ascii")
    name = der_name([("CN", common_name)])
    issuer = der_name([("DC", "local"), ("DC", "selftest"),
                       ("CN", "SELFTEST-CA")])
    tbs = der_seq(der_ctx(0, der_int(2)), der_int(secrets.randbits(64)),
                  der_seq(der_oid(OID_ECDSA_SHA256)), issuer,
                  der_seq(der_tlv(0x17, t0), der_tlv(0x17, t1)), name,
                  key.spki_der())
    cert = der_seq(tbs, der_seq(der_oid(OID_ECDSA_SHA256)),
                   der_bits(key.sign(tbs)))
    return base64.b64encode(cert).decode("ascii")
