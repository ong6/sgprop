"""SVY21 <-> WGS84, offline.

URA returns project coordinates in SVY21 (Singapore's Transverse Mercator
grid). This is the standard TM projection maths with SVY21's published
parameters, so no OneMap call is needed just to put a project on a map.
"""

from __future__ import annotations

import math

# SVY21 datum and projection parameters (SLA).
_A = 6378137.0
_F = 1 / 298.257223563
_ORIGIN_LAT = 1.366666
_ORIGIN_LON = 103.833333
_FALSE_N = 38744.572
_FALSE_E = 28001.642
_K = 1.0

_B = _A * (1 - _F)
_E2 = 2 * _F - _F * _F
_E4 = _E2 * _E2
_E6 = _E4 * _E2
_A0 = 1 - _E2 / 4 - 3 * _E4 / 64 - 5 * _E6 / 256
_A2 = 3.0 / 8 * (_E2 + _E4 / 4 + 15 * _E6 / 128)
_A4 = 15.0 / 256 * (_E4 + 3 * _E6 / 4)
_A6 = 35 * _E6 / 3072
_N = (_A - _B) / (_A + _B)
_N2, _N3, _N4 = _N ** 2, _N ** 3, _N ** 4
_G = _A * (1 - _N) * (1 - _N2) * (1 + 9 * _N2 / 4 + 225 * _N4 / 64) * (math.pi / 180)


def _meridian(lat_rad: float) -> float:
    return _A * (_A0 * lat_rad - _A2 * math.sin(2 * lat_rad)
                 + _A4 * math.sin(4 * lat_rad) - _A6 * math.sin(6 * lat_rad))


_M0 = _meridian(math.radians(_ORIGIN_LAT))


def to_latlon(northing: float, easting: float) -> tuple[float, float]:
    """SVY21 (N, E) in metres -> (lat, lon) in degrees."""
    n_prime = northing - _FALSE_N
    m_prime = _M0 + n_prime / _K
    sigma = (m_prime / _G) * math.pi / 180
    lat_prime = (sigma
                 + (3 * _N / 2 - 27 * _N3 / 32) * math.sin(2 * sigma)
                 + (21 * _N2 / 16 - 55 * _N4 / 32) * math.sin(4 * sigma)
                 + (151 * _N3 / 96) * math.sin(6 * sigma)
                 + (1097 * _N4 / 512) * math.sin(8 * sigma))

    sin_lp = math.sin(lat_prime)
    rho = _A * (1 - _E2) / (1 - _E2 * sin_lp ** 2) ** 1.5
    v = _A / math.sqrt(1 - _E2 * sin_lp ** 2)
    psi = v / rho
    t = math.tan(lat_prime)
    e_prime = easting - _FALSE_E
    x = e_prime / (_K * v)

    lat_t1 = t / (_K * rho) * (e_prime * x / 2)
    lat_t2 = (t / (_K * rho) * (e_prime * x ** 3 / 24)
              * (-4 * psi ** 2 + 9 * psi * (1 - t ** 2) + 12 * t ** 2))
    lat_t3 = (t / (_K * rho) * (e_prime * x ** 5 / 720)
              * (8 * psi ** 4 * (11 - 24 * t ** 2) - 12 * psi ** 3 * (21 - 71 * t ** 2)
                 + 15 * psi ** 2 * (15 - 98 * t ** 2 + 15 * t ** 4)
                 + 180 * psi * (5 * t ** 2 - 3 * t ** 4) + 360 * t ** 4))
    lat_t4 = (t / (_K * rho) * (e_prime * x ** 7 / 40320)
              * (1385 - 3633 * t ** 2 + 4095 * t ** 4 + 1575 * t ** 6))
    lat = lat_prime - lat_t1 + lat_t2 - lat_t3 + lat_t4

    sec_lp = 1 / math.cos(lat)
    lon_t1 = x * sec_lp
    lon_t2 = x ** 3 * sec_lp / 6 * (psi + 2 * t ** 2)
    lon_t3 = (x ** 5 * sec_lp / 120
              * (-4 * psi ** 3 * (1 - 6 * t ** 2) + psi ** 2 * (9 - 68 * t ** 2)
                 + 72 * psi * t ** 2 + 24 * t ** 4))
    lon_t4 = x ** 7 * sec_lp / 5040 * (61 + 662 * t ** 2 + 1320 * t ** 4 + 720 * t ** 6)
    lon = math.radians(_ORIGIN_LON) + lon_t1 - lon_t2 + lon_t3 - lon_t4
    return math.degrees(lat), math.degrees(lon)


def to_svy21(lat: float, lon: float) -> tuple[float, float]:
    """(lat, lon) in degrees -> SVY21 (N, E) in metres."""
    lat_r = math.radians(lat)
    sin_l = math.sin(lat_r)
    rho = _A * (1 - _E2) / (1 - _E2 * sin_l ** 2) ** 1.5
    v = _A / math.sqrt(1 - _E2 * sin_l ** 2)
    psi = v / rho
    t = math.tan(lat_r)
    w = math.radians(lon - _ORIGIN_LON)
    m = _meridian(lat_r)
    c = math.cos(lat_r)

    n1 = (w ** 2 / 2) * v * sin_l * c
    n2 = (w ** 4 / 24) * v * sin_l * c ** 3 * (4 * psi ** 2 + psi - t ** 2)
    n3 = (w ** 6 / 720) * v * sin_l * c ** 5 * (
        8 * psi ** 4 * (11 - 24 * t ** 2) - 28 * psi ** 3 * (1 - 6 * t ** 2)
        + psi ** 2 * (1 - 32 * t ** 2) - psi * 2 * t ** 2 + t ** 4)
    n4 = (w ** 8 / 40320) * v * sin_l * c ** 7 * (1385 - 3111 * t ** 2 + 543 * t ** 4 - t ** 6)
    north = _FALSE_N + _K * (m - _M0 + n1 + n2 + n3 + n4)

    e1 = (w ** 2 / 6) * c ** 2 * (psi - t ** 2)
    e2 = (w ** 4 / 120) * c ** 4 * (
        4 * psi ** 3 * (1 - 6 * t ** 2) + psi ** 2 * (1 + 8 * t ** 2) - psi * 2 * t ** 2 + t ** 4)
    e3 = (w ** 6 / 5040) * c ** 6 * (61 - 479 * t ** 2 + 179 * t ** 4 - t ** 6)
    east = _FALSE_E + _K * v * w * c * (1 + e1 + e2 + e3)
    return north, east
