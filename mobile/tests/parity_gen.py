# -*- coding: utf-8 -*-
"""يولّد حالات اختبار من دوال البرنامج نفسه (بايثون) — ليقارنها
`parity.js` بنسخة الجوال سطراً بسطر. أي اختلافٍ في منزلةٍ واحدة يُفشل الفحص.

    python mobile/tests/parity_gen.py > /tmp/cases.json
    node mobile/tests/parity.js /tmp/cases.json
"""
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from services import gold_math as gm          # noqa: E402
from services import karat_view as kv         # noqa: E402
from services import numfmt as nf             # noqa: E402

rnd = random.Random(int(os.environ.get("SEED", "1802")))
K = (18, 21, 22, 24)


def w(dec=None):
    d = dec if dec is not None else rnd.choice((0, 1, 2, 3, 3, 4))
    return round(rnd.uniform(0, 400), d)


EDGE = [0.0625, 2.675, 0.125, 1.005, 10.125, 2.5, 0.5, 1.5, 0.0005, 0.375,
        1234.5675, 99.995, 0.045, 7.0625, 15.4375, 0.1 + 0.2, 1e-7, 123456.789]
cases = []
for x in EDGE + [rnd.uniform(-1000, 1000) for _ in range(3000)] + \
        [round(rnd.uniform(-500, 500), rnd.randint(0, 5)) for _ in range(3000)] + \
        [rnd.randint(-2000, 2000) / 16 for _ in range(1000)]:
    for n in (0, 2, 3, 6, 9):
        cases.append(["round", [x, n], round(x, n)])
    cases.append(["f2", [x], nf.f2(x)])
    cases.append(["f2nosep", [x], nf.f2(x, sep=False)])

for _ in range(6000):
    k = rnd.choice(K)
    a, b, c = w(), w(), w()
    rate = rnd.choice((0.5, 0.5, 0.3, 0.0, 1.0, round(rnd.random(), 4)))
    wage = rnd.choice((0, round(rnd.uniform(0, 80), 2), round(rnd.uniform(0, 80), 3)))
    cases += [
        ["toBase", [a, k], gm.to_base_karat(a, k)],
        ["fromBase", [a, k], gm.from_base_karat(a, k)],
        ["stonesAfter", [c, rate], gm.stones_after_discount(c, rate)],
        ["registered", [a, b, c, rate], gm.registered_weight(a, b, c, rate)],
        ["standing", [a, b, c], gm.standing_gold(a, b, c)],
        ["totalWages", [wage, a], gm.total_wages(wage, a)],
        ["wagesVat", [round(a * 13.7, 2)], gm.wages_vat(round(a * 13.7, 2))],
        ["g", [a, k], kv.g(a, k)],
        ["store", [a, k], kv.store(a, k)],
        ["rate", [wage, k], kv.rate(wage, k)],
        ["rateStore", [wage, k], kv.rate_store(wage, k)],
        ["wageStore", [wage, k], round(float(wage) * kv.BASE / k, 6)],
    ]
    # سطر فاتورة كما يُرحَّل: وزن العرض ← 18، الأجر ← 18، الأجرة
    w18 = kv.store(a, k)
    r18 = round(float(wage) * kv.BASE / k, 6)
    cases.append(["lineWages", [a, wage, k], gm.total_wages(r18, round(w18, 3))])
    # سطر سند ذهب
    wt = round(float(a), 2)
    cases.append(["voucherEquiv", [a, k], gm.to_base_karat(wt, k)])

json.dump(cases, sys.stdout)
