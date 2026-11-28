"""EPSG:2278, NAD83 / Texas South Central (US survey feet), to (lat, lon).

Ellipsoidal Lambert conformal conic, two standard parallels (EPSG method 9802;
Snyder, USGS Professional Paper 1395, pp. 104–110). Parameters are from the
EPSG database bundled with PROJ 9.8.1; tests pin independently computed pyproj
values. https://proj.org/en/stable/operations/projections/lcc.html

NAD83 uses GRS80, not the WGS84 ellipsoid. After inverse projection we use the
EPSG:1188 NAD83-to-WGS84 null transformation, the default CONUS operation in
PROJ without grids. Its nominal accuracy is 4 m; agreement to under 1 m with
PROJ tests the arithmetic, not the datum or accuracy of a reported point.
No realization/epoch was supplied in the reports, so none is invented.
"""
from math import atan, atan2, cos, degrees, hypot, isfinite, log, pi, radians, sin, sqrt, tan

US_SURVEY_FOOT = 1200 / 3937
A = 6378137.0
FLATTENING = 1 / 298.257222101
E = sqrt(FLATTENING * (2 - FLATTENING))
PHI0, PHI1, PHI2 = map(radians, (27 + 50 / 60, 30 + 17 / 60, 28 + 23 / 60))
LAMBDA0 = radians(-99)
FALSE_EASTING = 1968500.0
FALSE_NORTHING = 13123333.333


def _t(phi: float) -> float:
    es = E * sin(phi)
    return tan(pi / 4 - phi / 2) / ((1 - es) / (1 + es)) ** (E / 2)


def _m(phi: float) -> float:
    return cos(phi) / sqrt(1 - (E * sin(phi)) ** 2)


N = log(_m(PHI1) / _m(PHI2)) / log(_t(PHI1) / _t(PHI2))
F = _m(PHI1) / (N * _t(PHI1) ** N)
RHO0 = A * F * _t(PHI0) ** N


def texas_south_central_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Return latitude, longitude in degrees. Input axes are X, Y in US feet.

    Reject nonfinite inputs and results outside EPSG:2278's area envelope.
    The caller must additionally verify its operator's service-area envelope.
    """
    if not (isfinite(easting) and isfinite(northing)):
        raise ValueError("State Plane coordinates must be finite")
    x = (easting - FALSE_EASTING) * US_SURVEY_FOOT
    y = RHO0 - (northing - FALSE_NORTHING) * US_SURVEY_FOOT
    rho = hypot(x, y)
    t = (rho / (A * F)) ** (1 / N)
    phi = pi / 2 - 2 * atan(t)
    for _ in range(15):
        es = E * sin(phi)
        nxt = pi / 2 - 2 * atan(t * ((1 - es) / (1 + es)) ** (E / 2))
        if abs(nxt - phi) < 1e-14:
            phi = nxt
            break
        phi = nxt
    lat, lon = degrees(phi), degrees(LAMBDA0 + atan2(x, y) / N)
    if not (27.78 <= lat <= 30.67 and -105 <= lon <= -93.76):
        raise ValueError("State Plane point outside Texas South Central")
    return lat, lon
