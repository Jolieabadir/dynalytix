"""
fdlibm's acos, ported so the worker's angles match the browser's to the bit.

V8 (and therefore every Chromium/Node build the frontend's golden file was
produced with) implements Math.acos with the fdlibm `__ieee754_acos` routine
(src/base/ieee754.cc). glibc's `acos`, which Python's math.acos calls, is a
different, correctly-rounded implementation, and the two disagree in the last
bit on a few percent of inputs. Both are "right" to within an ulp; only one of
them reproduces the frontend's CSV bytes. Since the angle columns are written
unrounded, this port is what makes the golden test pass byte for byte.

Straight transcription of e_acos.c (Sun Microsystems, 1993, freely
redistributable under its permissive notice), using struct to read and write
the IEEE-754 high/low words the algorithm keys on.
"""
from __future__ import annotations

import math
import struct

_pio2_hi = 1.57079632679489655800e+00
_pio2_lo = 6.12323399573676603587e-17
_pS0 = 1.66666666666666657415e-01
_pS1 = -3.25565818622400915405e-01
_pS2 = 2.01212532134862925881e-01
_pS3 = -4.00555345006794114027e-02
_pS4 = 7.91534994289814532176e-04
_pS5 = 3.47933107596021167570e-05
_qS1 = -2.40339491173441421878e+00
_qS2 = 2.02094576023350569471e+00
_qS3 = -6.88283971605453293030e-01
_qS4 = 7.70381505559019352791e-02


def _words(x: float):
    bits = struct.unpack('>Q', struct.pack('>d', x))[0]
    return (bits >> 32) & 0xFFFFFFFF, bits & 0xFFFFFFFF


def _from_words(hi: int, lo: int) -> float:
    return struct.unpack('>d', struct.pack('>Q', (hi << 32) | lo))[0]


def _pq(z: float):
    p = z * (_pS0 + z * (_pS1 + z * (_pS2 + z * (_pS3 + z * (_pS4 + z * _pS5)))))
    q = 1.0 + z * (_qS1 + z * (_qS2 + z * (_qS3 + z * _qS4)))
    return p, q


def acos(x: float) -> float:
    """fdlibm __ieee754_acos(x), bit-identical to V8's Math.acos."""
    hx, lx = _words(x)
    ix = hx & 0x7FFFFFFF
    if ix >= 0x3FF00000:  # |x| >= 1
        if ((ix - 0x3FF00000) | lx) == 0:
            if not (hx & 0x80000000):
                return 0.0  # acos(1) = 0
            return math.pi + 2.0 * _pio2_lo  # acos(-1) = pi
        return math.nan  # acos(|x| > 1) is NaN
    if ix < 0x3FE00000:  # |x| < 0.5
        if ix <= 0x3C600000:  # |x| < 2**-57
            return _pio2_hi + _pio2_lo
        z = x * x
        p, q = _pq(z)
        r = p / q
        return _pio2_hi - (x - (_pio2_lo - x * r))
    if hx & 0x80000000:  # x < -0.5
        z = (1.0 + x) * 0.5
        p, q = _pq(z)
        s = math.sqrt(z)
        r = p / q
        w = r * s - _pio2_lo
        return math.pi - 2.0 * (s + w)
    # x > 0.5
    z = (1.0 - x) * 0.5
    s = math.sqrt(z)
    df_hi, _ = _words(s)
    df = _from_words(df_hi, 0)
    c = (z - df * df) / (s + df)
    p, q = _pq(z)
    r = p / q
    w = r * s + c
    return 2.0 * (df + w)
