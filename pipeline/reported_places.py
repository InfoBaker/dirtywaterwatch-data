"""Public treatment of places we geolocate, including cached pre-policy rows.

Agency geocodes have no `geolocation` block and are source points. Our street
lookups keep their coordinates and are exported as listings without point markers
because a derived place does not establish the spill point.
"""
from __future__ import annotations

BASES = {
    'address': 'Our approximate location uses a Census address-range match.',
    'intersection': 'Our approximate location uses the reported intersection on OpenStreetMap.',
    'street': 'Our approximate location uses the reported street on OpenStreetMap.',
    'pump_station': 'Our approximate location uses the reported pump station or its street on OpenStreetMap.',
    'plant': 'Our approximate location uses the treatment plant the report names, from OpenStreetMap or EPA.',
}


def public_place(row: dict, *, listing: bool = False) -> dict:
    """Return a copy; never treat an agency's coord_source=geocode as our lookup.

    The build keeps the lookup coordinates, but public page listings
    have no point. A legacy plant fallback loses both its point and traced water.
    Only waters identified by the reports survive for our derived listings.
    """
    geo = row.get('geolocation') or {}
    kind = geo.get('kind') or row.get('place_method')
    stand_in = row.get('stand_in') or kind == 'frs_stand_in'
    if not geo and not kind and not stand_in:
        return row.copy()
    out = row.copy()
    slugs = [] if row.get('reached_water') == 'no' else list(row.get('reports_water_slugs') or [])
    out.update(on_map=False, water_slugs=slugs, water_slug=next(iter(slugs), None),
               water_match='reports' if slugs else 'none', match='reports' if slugs else 'none',
               place_tier=3 if slugs else (5 if stand_in else 4),
               place_method='plant_stand_in_removed' if stand_in else kind,
               place_precision_m=None if stand_in else geo.get('precision_m', row.get('place_precision_m')))
    if stand_in:
        basis = 'Our earlier treatment plant fallback has been removed; the report supplies no spill point.'
        out.update(lat=None, lon=None, receiving_water=None, water=None, label='Report without a spill point')
    else:
        basis = BASES.get(kind, 'Our approximate location uses the place the report names.')
        for key in ('lat', 'lon'):
            out[key] = None if listing else row.get(key)
    out['place_basis'] = basis + (' Listed on the water linked to the reports.' if slugs else ' Listed with the operator.')
    out['method'] = out['place_basis']
    return out
