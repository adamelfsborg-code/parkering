"""SWEREF99 TM (EPSG:3006) -> WGS84, Lantmäteriets formler för Gauss–Krüger."""
import math

_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_N = _F / (2 - _F)
_AR = _A / (1 + _N) * (1 + _N ** 2 / 4 + _N ** 4 / 64)
_D = (_N / 2 - 2 * _N ** 2 / 3 + 37 * _N ** 3 / 96 - _N ** 4 / 360,
      _N ** 2 / 48 + _N ** 3 / 15 - 437 * _N ** 4 / 1440,
      17 * _N ** 3 / 480 - 37 * _N ** 4 / 840,
      4397 * _N ** 4 / 161280)
_AS = _E2 + _E2 ** 2 + _E2 ** 3 + _E2 ** 4
_BS = -(7 * _E2 ** 2 + 17 * _E2 ** 3 + 30 * _E2 ** 4) / 6
_CS = (224 * _E2 ** 3 + 889 * _E2 ** 4) / 120
_DS = -(4279 * _E2 ** 4) / 1260
_K0, _FE, _L0 = 0.9996, 500000.0, math.radians(15.0)


def to_wgs84(easting, northing):
    xi = northing / (_K0 * _AR)
    eta = (easting - _FE) / (_K0 * _AR)
    xp, ep = xi, eta
    for i, d in enumerate(_D, start=1):
        xp -= d * math.sin(2 * i * xi) * math.cosh(2 * i * eta)
        ep -= d * math.cos(2 * i * xi) * math.sinh(2 * i * eta)
    phi_s = math.asin(math.sin(xp) / math.cosh(ep))
    dl = math.atan(math.sinh(ep) / math.cos(xp))
    s2 = math.sin(phi_s) ** 2
    lat = phi_s + math.sin(phi_s) * math.cos(phi_s) * (_AS + _BS * s2 + _CS * s2 ** 2 + _DS * s2 ** 3)
    return math.degrees(lat), math.degrees(_L0 + dl)
