# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# StaticPython compatibility implementation derived from Hypothesis 6.164.0.
from __future__ import annotations

import math
import sys


def cathetus(h: float, a: float) -> float:
    if math.isnan(h):
        return math.nan
    if math.isinf(h):
        return math.nan if math.isinf(a) else math.inf

    h = abs(h)
    a = abs(a)
    if h < a:
        return math.nan

    sqrt_max = math.sqrt(sys.float_info.max)
    sqrt_min = math.sqrt(sys.float_info.min)
    if h > sqrt_max:
        if h > sys.float_info.max / 2.0:
            result = math.sqrt(h - a) * math.sqrt(h / 2.0 + a / 2.0) * math.sqrt(2.0)
        else:
            result = math.sqrt(h - a) * math.sqrt(h + a)
    elif h < sqrt_min:
        result = math.sqrt(h - a) * math.sqrt(h + a)
    else:
        result = math.sqrt((h - a) * (h + a))
    return math.nan if math.isnan(result) else min(result, h)
