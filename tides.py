import requests
import json
import math
from datetime import datetime
from models import db, TideCache

ADMIRALTY_BASE = "https://admiraltyapi.azure-api.net/uktidalapi/api/V1"

# If nearest station is further than this, tide data is likely irrelevant
MAX_STATION_DISTANCE_KM = 100

TIDE_COLOURS = {
    'too_low':  '#ffcccc',   # red   — rocks exposed
    'usable':   '#c8f7c5',   # green — within usable range
    'too_high': '#c5e1f7',   # blue  — no beach
    'no_data':  '#f5f5f5',   # grey  — no tide info
}


def _headers(api_key):
    return {'Ocp-Apim-Subscription-Key': api_key}


def _haversine(lat1, lon1, lat2, lon2):
    """Distance in km between two points."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def find_nearest_station(lat, lng, api_key):
    """Return (station_dict, distance_km) for the closest tidal station."""
    resp = requests.get(f"{ADMIRALTY_BASE}/stations",
                        headers=_headers(api_key), timeout=15)
    resp.raise_for_status()
    stations = resp.json().get('features', [])

    nearest, min_dist = None, float('inf')
    for s in stations:
        coords = s['geometry']['coordinates']   # [lng, lat]
        dist = _haversine(lat, lng, coords[1], coords[0])
        if dist < min_dist:
            min_dist = dist
            nearest = s
    return nearest, min_dist


def fetch_and_cache_tides(spot, api_key):
    """Fetch tidal events for the nearest station and cache them."""
    cache = TideCache.query.filter_by(spot_id=spot.id).first()

    # Only re-find the station if we don't have one yet
    if cache and cache.station_id:
        station_id   = cache.station_id
        station_name = cache.station_name
        distance_km  = cache.station_distance_km
    else:
        station, distance_km = find_nearest_station(
            spot.latitude, spot.longitude, api_key)
        if not station:
            return
        if distance_km > MAX_STATION_DISTANCE_KM:
            print(f"[Tides] {spot.name}: nearest station is {distance_km:.0f}km away — skipping")
            # Record that we checked so the app knows tide data is unavailable
            if not cache:
                db.session.add(TideCache(spot_id=spot.id, station_distance_km=distance_km))
            else:
                cache.station_distance_km = distance_km
            db.session.commit()
            return
        props        = station['properties']
        station_id   = props['Id']
        station_name = props['Name']
        hat, lat     = _fetch_hat_lat(props, station_id, api_key)
        if cache:
            cache.station_hat = hat
            cache.station_lat = lat
        # (will be committed below with the rest of the cache update)

    # Fetch 4 days of tidal events (covers our 3-day forecast window)
    resp = requests.get(
        f"{ADMIRALTY_BASE}/stations/{station_id}/tidalevents",
        headers=_headers(api_key),
        params={'duration': 4},  # days (allowed range: 1-7)
        timeout=15)
    resp.raise_for_status()
    events = resp.json()

    if cache:
        cache.station_id          = station_id
        cache.station_name        = station_name
        cache.station_distance_km = distance_km
        cache.fetched_at          = datetime.utcnow()
        cache.events_json         = json.dumps(events)
    else:
        db.session.add(TideCache(
            spot_id=spot.id,
            station_id=station_id,
            station_name=station_name,
            station_distance_km=distance_km,
            events_json=json.dumps(events),
        ))
    db.session.commit()
    print(f"[Tides] Updated {spot.name} → {station_name} ({distance_km:.1f} km)")


def _parse_events(events_json):
    """Parse stored JSON events into sorted list of dicts."""
    raw = json.loads(events_json)
    parsed = []
    for e in raw:
        dt_str = e['DateTime'].replace('Z', '')
        parsed.append({
            'dt':     datetime.fromisoformat(dt_str),
            'height': e['Height'],
            'type':   e['EventType'],   # 'HighWater' or 'LowWater'
        })
    parsed.sort(key=lambda x: x['dt'])
    return parsed


def interpolate_height(events, dt):
    """
    Cosine interpolation of tide height at a given datetime.
    Returns None if events don't cover the requested time.
    """
    before, after = None, None
    for e in events:
        if e['dt'] <= dt:
            before = e
        elif after is None:
            after = e
            break

    if before is None or after is None:
        return None

    total   = (after['dt'] - before['dt']).total_seconds()
    elapsed = (dt - before['dt']).total_seconds()
    t       = elapsed / total if total else 0

    height = (before['height']
              + (after['height'] - before['height'])
              * (1 - math.cos(math.pi * t)) / 2)
    return round(height, 2)


def tide_percentage(height, ref_low, ref_high):
    """Express height as % between ref_low and ref_high.

    When called with HAT/LAT:  0% = Lowest Astronomical Tide, 100% = Highest Astronomical Tide.
    Values above 100% indicate a storm surge above HAT.
    Falls back to daily high/low range if HAT/LAT are not yet cached for a spot.
    """
    tidal_range = ref_high - ref_low
    if tidal_range == 0:
        return 50
    return round((height - ref_low) / tidal_range * 100)


def tide_colour(pct, spot):
    """Return a background colour based on how the tide % compares to spot limits."""
    if pct < spot.min_tide_percent:
        return TIDE_COLOURS['too_low']
    elif pct > spot.max_tide_percent:
        return TIDE_COLOURS['too_high']
    else:
        return TIDE_COLOURS['usable']


def generate_dummy_tide_slots(spot, target_dates):
    """
    Generate realistic-looking dummy tide data for display purposes.
    Uses a semidiurnal (two high tides per day) cosine pattern typical of UK coasts.
    """
    result = {}
    # Typical UK tidal parameters
    mean_height  = 2.8   # mean sea level (m)
    amplitude    = 2.3   # tidal range / 2
    period_hours = 12.42 # lunar semidiurnal period

    for i, date in enumerate(target_dates):
        date_key  = date.strftime('%Y-%m-%d')
        day_low   = mean_height - amplitude
        day_high  = mean_height + amplitude
        result[date_key] = {}

        for hour in range(24):
            # Phase shifts slightly each day (tides advance ~50 mins/day)
            phase = (hour + i * 0.83) / period_hours * 2 * math.pi
            height = round(mean_height + amplitude * math.cos(phase), 2)
            pct    = tide_percentage(height, day_low, day_high)
            result[date_key][hour] = {
                'height':  height,
                'pct':     pct,
                'colour':  tide_colour(pct, spot),
            }
    return result


def _fetch_hat_lat(station_props, station_id, api_key):
    """Return (hat, lat) for a station.

    Tries the station properties from the list response first.
    If not present, fetches the individual station endpoint.
    Returns (None, None) if unavailable.
    """
    hat = station_props.get('HighestAstronomicalTide')
    lat = station_props.get('LowestAstronomicalTide')
    if hat is not None:
        return hat, lat or 0.0
    try:
        resp = requests.get(f"{ADMIRALTY_BASE}/stations/{station_id}",
                            headers=_headers(api_key), timeout=10)
        resp.raise_for_status()
        props = resp.json().get('properties', {})
        hat = props.get('HighestAstronomicalTide')
        lat = props.get('LowestAstronomicalTide', 0.0)
        return hat, lat or 0.0
    except Exception as e:
        print(f"[Tides] Could not fetch HAT/LAT for station {station_id}: {e}")
        return None, None


def _get_station_id(spot, api_key):
    """Return the nearest station ID for a spot.

    Caches station metadata (including HAT/LAT) to avoid scanning all stations
    on every page load.
    """
    cache = TideCache.query.filter_by(spot_id=spot.id).first()
    if cache and cache.station_id:
        return cache.station_id, cache.station_name

    station, distance_km = find_nearest_station(spot.latitude, spot.longitude, api_key)
    if not station or distance_km > MAX_STATION_DISTANCE_KM:
        return None, None

    props        = station['properties']
    station_id   = props['Id']
    station_name = props['Name']
    hat, lat     = _fetch_hat_lat(props, station_id, api_key)

    if cache:
        cache.station_id          = station_id
        cache.station_name        = station_name
        cache.station_distance_km = distance_km
        cache.station_hat         = hat
        cache.station_lat         = lat
    else:
        db.session.add(TideCache(
            spot_id=spot.id,
            station_id=station_id,
            station_name=station_name,
            station_distance_km=distance_km,
            station_hat=hat,
            station_lat=lat,
        ))
    db.session.commit()
    return station_id, station_name


def _events_to_slots(events, spot, target_dates, hat=None, lat=None):
    """Convert a list of parsed tidal events into the slot dict we need.

    Uses HAT/LAT as the percentage reference when available (consistent across
    neap and spring tides).  Falls back to the day's own high/low range if
    HAT/LAT have not yet been cached for this station.
    """
    result = {}
    for target_date in target_dates:
        date_key   = target_date.strftime('%Y-%m-%d')
        day_events = [e for e in events if e['dt'].date() == target_date]
        if not day_events:
            continue

        if hat is not None:
            ref_low  = lat if lat is not None else 0.0
            ref_high = hat
        else:
            ref_low  = min(e['height'] for e in day_events)
            ref_high = max(e['height'] for e in day_events)

        result[date_key] = {}
        for hour in range(24):
            dt     = datetime(target_date.year, target_date.month, target_date.day, hour)
            height = interpolate_height(events, dt)
            if height is None:
                continue
            pct = tide_percentage(height, ref_low, ref_high)
            result[date_key][hour] = {
                'height': height,
                'pct':    pct,
                'colour': tide_colour(pct, spot),
            }
    return result


def get_tide_slots(spot, target_dates):
    """
    Always calls the API live for fresh data.
    If the API is unavailable, falls back to the last successfully received data.
    Returns empty dict if neither is available.
    """
    import os
    api_key = os.environ.get('ADMIRALTY_API_KEY', '')
    cache   = TideCache.query.filter_by(spot_id=spot.id).first()

    hat = cache.station_hat if cache else None
    lat = cache.station_lat if cache else None

    if not api_key:
        print(f"[Tides] No API key set.")
        return _events_to_slots(_parse_events(cache.events_json), spot, target_dates,
                                hat=hat, lat=lat) if (cache and cache.events_json) else {}

    try:
        station_id, _ = _get_station_id(spot, api_key)
        if not station_id:
            return {}

        # Re-read cache in case _get_station_id just populated HAT/LAT
        cache = TideCache.query.filter_by(spot_id=spot.id).first()
        hat   = cache.station_hat if cache else None
        lat   = cache.station_lat if cache else None

        # Always fetch live tidal events
        resp = requests.get(
            f"{ADMIRALTY_BASE}/stations/{station_id}/tidalevents",
            headers=_headers(api_key),
            params={'duration': 4},
            timeout=10
        )
        resp.raise_for_status()
        raw_events = resp.json()

        # Save as fallback for when API is unavailable
        if cache:
            cache.fetched_at  = datetime.utcnow()
            cache.events_json = json.dumps(raw_events)
            db.session.commit()

        events = _parse_events(json.dumps(raw_events))
        print(f"[Tides] Live data fetched for {spot.name}")
        return _events_to_slots(events, spot, target_dates, hat=hat, lat=lat)

    except Exception as e:
        print(f"[Tides] API unavailable for {spot.name}: {e}")
        if cache and cache.events_json:
            print(f"[Tides] Using last received data for {spot.name}")
            return _events_to_slots(_parse_events(cache.events_json), spot, target_dates,
                                    hat=hat, lat=lat)
        print(f"[Tides] No fallback data available for {spot.name}")
        return {}
