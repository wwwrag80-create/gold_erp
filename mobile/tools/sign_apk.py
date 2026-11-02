# -*- coding: utf-8 -*-
"""توقيع ملف تثبيت أندرويد بمفتاح المالك — APK Signature Scheme v2.

البناء يجري على خوادم GitHub ويخرج **غير موقّع** (المستودع عام فلا مفتاح
فيه). هذا الأداة توقّعه خارج المستودع بمفتاحٍ ثابت — والثبات شرطٌ لتحديث
التطبيق فوق نفسه دون حذف بياناته من الجوال.

    python mobile/tools/sign_apk.py --key DIR in.apk out.apk
    python mobile/tools/sign_apk.py --key DIR --v1 in.apk out.apk   # v1 + v2 (ملف المتاجر)
    python mobile/tools/sign_apk.py --key DIR --new-key        # مفتاحٌ جديد

`DIR` يحوي `key.pem` (المفتاح الخاص) و`cert.der` (الشهادة). يُنشأ مرة
واحدة ويُحفظ عند المالك؛ ضياعه يعني أن التحديث التالي يتطلّب حذف التطبيق
ثم استرجاع النسخة الاحتياطية.

المرجع: https://source.android.com/docs/security/features/apksigning/v2
(التنفيذ يتبع `V2SchemeSigner` في apksig سطراً بسطر).
"""
import argparse
import datetime
import hashlib
import struct
import sys
import zipfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

V2_ID = 0x7109871A
RSA_PKCS1_SHA256 = 0x0103
MAGIC = b"APK Sig Block 42"
CHUNK = 1024 * 1024


def lp(b):                                   # length-prefixed (uint32)
    return struct.pack("<I", len(b)) + b


def seq(items):                              # sequence of length-prefixed
    return b"".join(lp(x) for x in items)


def pairs(items):                            # (id, bytes) pairs, each length-prefixed
    return b"".join(lp(struct.pack("<I", i) + lp(v)) for i, v in items)


def find_eocd(data):
    i = data.rfind(b"PK\x05\x06", max(0, len(data) - 65557))
    while i >= 0:
        clen = struct.unpack_from("<H", data, i + 20)[0]
        if i + 22 + clen == len(data):
            return i
        i = data.rfind(b"PK\x05\x06", 0, i)
    raise ValueError("ليس ملف ZIP صالحاً (لا EOCD)")


def check_alignment(data):
    """المخزَّن بلا ضغط يبدأ على حدّ 4 بايت (شرط أندرويد 11+ لـresources.arsc)."""
    bad = []
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as z:
        for info in z.infolist():
            if info.compress_type != zipfile.ZIP_STORED:
                continue
            off = info.header_offset
            n, e = struct.unpack_from("<HH", data, off + 26)
            start = off + 30 + n + e
            if start % 4:
                bad.append(info.filename)
    return bad


def digest_chunks(sections):
    chunk_digests = []
    for sec in sections:
        for i in range(0, len(sec), CHUNK):
            c = sec[i:i + CHUNK]
            chunk_digests.append(hashlib.sha256(b"\xa5" + struct.pack("<I", len(c)) + c).digest())
    return hashlib.sha256(b"\x5a" + struct.pack("<I", len(chunk_digests))
                          + b"".join(chunk_digests)).digest()


def sign(data, key, cert_der):
    if data[:2] != b"PK":
        raise ValueError("ليس ملف APK")
    eocd = find_eocd(data)
    cd_off, = struct.unpack_from("<I", data, eocd + 16)
    if data[cd_off - 16:cd_off] == MAGIC:
        raise ValueError("الملف موقّعٌ مسبقاً (فيه APK Signing Block)")
    bad = check_alignment(data)
    if bad:
        raise ValueError("ملفاتٌ مخزّنة بلا محاذاة 4 بايت: " + ", ".join(bad[:5]))
    before, cd, eo = data[:cd_off], data[cd_off:eocd], data[eocd:]
    digest = digest_chunks([before, cd, eo])     # EOCD يشير إلى cd_off = بداية الكتلة

    pub = key.public_key().public_bytes(serialization.Encoding.DER,
                                        serialization.PublicFormat.SubjectPublicKeyInfo)
    signed_data = seq([pairs([(RSA_PKCS1_SHA256, digest)]), seq([cert_der]), b""])
    sig = key.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())
    signer = seq([signed_data, pairs([(RSA_PKCS1_SHA256, sig)]), pub])
    value = lp(seq([signer]))
    pair = struct.pack("<Q", 4 + len(value)) + struct.pack("<I", V2_ID) + value
    size = len(pair) + 8 + 16
    block = struct.pack("<Q", size) + pair + struct.pack("<Q", size) + MAGIC
    new_eo = bytearray(eo)
    struct.pack_into("<I", new_eo, 16, cd_off + len(block))
    return before + block + cd + bytes(new_eo)


def _wrap72(line):
    """سطر ملف MANIFEST: 72 بايتاً على الأكثر، والتكملة تبدأ بمسافة (لا يُقطع حرف UTF-8)."""
    out, first = [], True
    while line:
        n = 72 if first else 71
        if len(line) > n:
            while n > 1 and (line[n] & 0xC0) == 0x80:     # لا نقطع داخل حرفٍ متعدد البايتات
                n -= 1
        out.append((b"" if first else b" ") + line[:n] + b"\r\n")
        line, first = line[n:], False
    return b"".join(out)


def v1_sign(data, key, cert_der):
    """توقيع JAR (v1) للمتاجر وأدوات الفحص القديمة: META-INF/MANIFEST.MF وCERT.SF وCERT.RSA
    تُضاف في آخر الملف (فتبقى إزاحات الملفات الأخرى ومحاذاتها كما هي)، وفي CERT.SF
    «X-Android-APK-Signed: 2» — فيُرفض الملف إن نُزع منه توقيع v2 الذي يُضاف بعده."""
    import base64
    import io
    from cryptography.hazmat.primitives.serialization import pkcs7

    b64 = lambda b: base64.b64encode(hashlib.sha256(b).digest())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [i.filename for i in z.infolist() if not i.is_dir()]
        if any(n.upper().startswith("META-INF/") and n.upper().rsplit(".", 1)[-1] in ("SF", "RSA", "DSA", "EC", "MF")
               for n in names):
            raise ValueError("الملف موقّعٌ مسبقاً (فيه META-INF)")
        sections = [(n, _wrap72(b"Name: " + n.encode("utf-8")) + b"SHA-256-Digest: " + b64(z.read(n)) + b"\r\n\r\n")
                    for n in names]
    mf = b"Manifest-Version: 1.0\r\nCreated-By: 1.0 (Android)\r\n\r\n" + b"".join(s for _, s in sections)
    sf = (b"Signature-Version: 1.0\r\nCreated-By: 1.0 (Android)\r\nSHA-256-Digest-Manifest: " + b64(mf)
          + b"\r\nX-Android-APK-Signed: 2\r\n\r\n"
          + b"".join(_wrap72(b"Name: " + n.encode("utf-8")) + b"SHA-256-Digest: " + b64(s) + b"\r\n\r\n"
                     for n, s in sections))
    cert = x509.load_der_x509_certificate(cert_der)
    rsa_block = (pkcs7.PKCS7SignatureBuilder().set_data(sf).add_signer(cert, key, hashes.SHA256())
                 .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature,
                                                    pkcs7.PKCS7Options.NoAttributes]))
    return _prepend(data, [("META-INF/MANIFEST.MF", mf), ("META-INF/CERT.SF", sf), ("META-INF/CERT.RSA", rsa_block)])


def _prepend(data, entries):
    """يضع ملفات التوقيع أول الملف (كما يفعل jarsigner — فيقرؤها JarInputStream أيضاً)، ويُزاح
    الباقي كما هو بمقدارٍ من مضاعفات 4 (حقل محاذاةٍ 0xD935 عند الحاجة) فتبقى محاذاته."""
    import zlib
    eocd = find_eocd(data)
    cd_off, = struct.unpack_from("<I", data, eocd + 16)
    n_old, = struct.unpack_from("<H", data, eocd + 10)
    dos_time, dos_date = (1 << 11) | (1 << 5) | 1, ((1981 - 1980) << 9) | (1 << 5) | 1
    recs = []
    for name, body in entries:
        co = zlib.compressobj(9, zlib.DEFLATED, -15)
        comp = co.compress(body) + co.flush()
        recs.append([name.encode(), body, comp, zlib.crc32(body) & 0xFFFFFFFF, b""])
    size = sum(30 + len(r[0]) + len(r[2]) for r in recs)
    if size % 4:
        p = (-(size + 6)) % 4
        recs[-1][4] = struct.pack("<HHH", 0xD935, 2 + p, 4) + b"\0" * p
    local, central, off = bytearray(), bytearray(), 0
    for name, body, comp, crc, extra in recs:
        local += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, dos_time, dos_date, crc,
                             len(comp), len(body), len(name), len(extra)) + name + extra + comp
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 8, dos_time, dos_date, crc,
                               len(comp), len(body), len(name), 0, 0, 0, 0, 0, off) + name
        off = len(local)
    shift = len(local)
    assert shift % 4 == 0
    old_cd = bytearray(data[cd_off:eocd])
    i = 0
    for _ in range(n_old):                      # إزاحة كل سجلٍّ قديم في الفهرس
        assert struct.unpack_from("<I", old_cd, i)[0] == 0x02014B50
        n, m, k = struct.unpack_from("<HHH", old_cd, i + 28)
        o, = struct.unpack_from("<I", old_cd, i + 42)
        struct.pack_into("<I", old_cd, i + 42, o + shift)
        i += 46 + n + m + k
    assert i == len(old_cd)
    cd = bytes(central) + bytes(old_cd)
    eo = bytearray(data[eocd:])
    struct.pack_into("<HHII", eo, 8, n_old + len(recs), n_old + len(recs), len(cd), shift + cd_off)
    return bytes(local) + data[:cd_off] + cd + bytes(eo)


def new_key(d):
    d.mkdir(parents=True, exist_ok=True)
    k = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Jadeite Mobile"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Jadeite")])
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(k.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=365 * 60))
            .sign(k, hashes.SHA256()))
    (d / "key.pem").write_bytes(k.private_bytes(serialization.Encoding.PEM,
                                                serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()))
    (d / "cert.der").write_bytes(cert.public_bytes(serialization.Encoding.DER))
    print("مفتاحٌ جديد في", d, "· بصمة الشهادة SHA-256:",
          hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest())


def load_key(d):
    key = serialization.load_pem_private_key((d / "key.pem").read_bytes(), password=None)
    return key, (d / "cert.der").read_bytes()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, type=Path)
    ap.add_argument("--new-key", action="store_true")
    ap.add_argument("--v1", action="store_true", help="توقيع v1 أيضاً (للمتاجر: شاومي وغيرها) ثم v2")
    ap.add_argument("inp", nargs="?")
    ap.add_argument("out", nargs="?")
    a = ap.parse_args(argv)
    if a.new_key:
        if (a.key / "key.pem").exists():
            sys.exit("يوجد مفتاحٌ هنا — لا يُستبدل (استبداله يمنع تحديث التطبيق المثبّت)")
        new_key(a.key)
        return
    key, cert = load_key(a.key)
    data = Path(a.inp).read_bytes()
    if a.v1:
        data = v1_sign(data, key, cert)
    out = sign(data, key, cert)
    Path(a.out).write_bytes(out)
    print("وُقّع:", a.out, len(out), "بايت · SHA-256:", hashlib.sha256(out).hexdigest())


if __name__ == "__main__":
    main()
