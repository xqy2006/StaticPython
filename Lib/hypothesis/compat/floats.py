# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
#
# StaticPython compatibility implementation derived from Hypothesis 6.164.0.
from __future__ import annotations

import math
import struct


_FORMATS = {16: ">e", 32: ">f", 64: ">d"}


def _format(width: int) -> str:
    try:
        return _FORMATS[width]
    except KeyError as exc:
        raise ValueError(f"invalid width {width}") from exc


def float_to_int(value: float, width: int = 64) -> int:
    packed = struct.pack(_format(width), value)
    return int.from_bytes(packed, "big")


def int_to_float(value: int, width: int = 64) -> float:
    packed = value.to_bytes(width // 8, "big")
    return struct.unpack(_format(width), packed)[0]


def float_of(value: float, width: int) -> float:
    if width == 64:
        return value
    return int_to_float(float_to_int(value, width), width)


def is_negative(value: float) -> bool:
    return math.copysign(1.0, value) < 0.0


def count_between_floats(x: float, y: float, width: int = 64) -> int:
    assert x <= y
    if is_negative(x):
        if is_negative(y):
            return float_to_int(x, width) - float_to_int(y, width) + 1
        return count_between_floats(x, -0.0, width) + count_between_floats(0.0, y, width)
    assert not is_negative(y)
    return float_to_int(y, width) - float_to_int(x, width) + 1


def next_up(value: float, width: int = 64) -> float:
    if math.isnan(value) or (math.isinf(value) and value > 0.0):
        return value
    if value == 0.0 and is_negative(value):
        return 0.0
    bits = float_to_int(value, width)
    sign_bit = 1 << (width - 1)
    signed = bits if bits < sign_bit else bits - (1 << width)
    signed = signed + 1 if signed >= 0 else signed - 1
    return int_to_float(signed & ((1 << width) - 1), width)


def next_down(value: float, width: int = 64) -> float:
    return -next_up(-value, width)


def width_smallest_normals(width: int) -> float:
    try:
        exponent = {16: -14, 32: -126, 64: -1022}[width]
    except KeyError as exc:
        raise ValueError(f"invalid width {width}") from exc
    return 2.0**exponent


def next_down_normal(value: float, width: int, *, allow_subnormal: bool) -> float:
    result = next_down(value, width)
    smallest = width_smallest_normals(width)
    if not allow_subnormal and 0.0 < abs(result) < smallest:
        return 0.0 if result > 0.0 else -smallest
    return result


def next_up_normal(value: float, width: int, *, allow_subnormal: bool) -> float:
    return -next_down_normal(-value, width, allow_subnormal=allow_subnormal)
