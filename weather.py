import requests
import json
import os
from datetime import datetime
from models import db, WeatherCache

WEATHER_API = "https://api.open-meteo.com/v1/forecast"
MARINE_API  = "https://marine-api.open-meteo.com/v1/marine"

WMO_EMOJI = {
    0: '☀️', 1: '🌤️', 2: '⛅', 3: '🌥️',
    45: '🌫️', 48: '🌫️',
    51: '🌦️', 53: '🌦️', 55: '🌧️',
    61: '🌧️', 63: '🌧️', 65: '🌧️',
    71: '❄️', 73: '❄️', 75: '❄️',
    80: '🌦️', 81: '🌧️', 82: '🌧️',
    95: '⛈️', 96: '⛈️', 99: '⛈️'
}

COMPASS = ['N','NNE','NE','ENE','E','ESE','SE','SSE',
           'S','SSW','SW','WSW','W','WNW','NW','NNW']

RATING_COLOURS = {
    'perfect':     '#c8f7c5',
    'good':        '#c5e1f7',
    'okay':        '#fff9c5',
    'poor':        '#ffe0b2',
    'dangerous':   '#e0e0e0',
    'out_of_range':'#f5f5f5',
}


def degrees_to_compass(deg):
    return COMPASS[round(deg / 22.5) % 16]


def rate_slot(spot, wind_speed, wind_dir_compass):
    """Return a rating string for one time slot."""
    if wind_speed < spot.min_wind or wind_speed > spot.max_wind:
        return 'out_of_range'

    def dirs(field):
        v = getattr(spot, field, '') or ''
        return [d.strip() for d in v.split(',') if d.strip()]

    if wind_dir_compass in dirs('perfect_directions'):   return 'perfect'
    if wind_dir_compass in dirs('good_directions'):      return 'good'
    if wind_dir_compass in dirs('okay_directions'):      return 'okay'
    if wind_dir_compass in dirs('poor_directions'):      return 'poor'
    return 'dangerous'


def fetch_and_cache_weather(spot):
    """Call Open-Meteo (+ marine) and store result in WeatherCache."""
    weather_resp = requests.get(WEATHER_API, params={
        'latitude':        spot.latitude,
        'longitude':       spot.longitude,
        'hourly':          'windspeed_10m,winddirection_10m,windgusts_10m,weathercode,temperature_2m',
        'daily':           'sunrise,sunset',
        'wind_speed_unit': 'kn',
        'timezone':        'Europe/London',
        'forecast_days':   3,
    }, timeout=10)
    weather_data = weather_resp.json()

    marine_data = None
    try:
        marine_resp = requests.get(MARINE_API, params={
            'latitude':      spot.latitude,
            'longitude':     spot.longitude,
            'hourly':        'wave_height',
            'timezone':      'Europe/London',
            'forecast_days': 3,
        }, timeout=10)
        marine_data = marine_resp.json()
        if 'error' in marine_data:
            marine_data = None
    except Exception:
        pass

    payload = json.dumps({'weather': weather_data, 'marine': marine_data})

    cache = WeatherCache.query.filter_by(spot_id=spot.id).first()
    if cache:
        cache.fetched_at    = datetime.utcnow()
        cache.forecast_json = payload
    else:
        db.session.add(WeatherCache(spot_id=spot.id, forecast_json=payload))
    db.session.commit()


def get_forecast_table(spot):
    """
    Return (days, fetched_at) where days is a list of dicts, one per day,
    each containing sunrise, sunset and a list of hourly slots (daylight only).
    Returns (None, None) if no cache exists yet.
    """
    cache = WeatherCache.query.filter_by(spot_id=spot.id).first()
    if not cache:
        return None, None

    data   = json.loads(cache.forecast_json)
    hourly = data['weather'].get('hourly', {})
    daily  = data['weather'].get('daily',  {})

    times  = hourly.get('time', [])
    speeds = hourly.get('windspeed_10m', [])
    dirs   = hourly.get('winddirection_10m', [])
    gusts  = hourly.get('windgusts_10m', [])
    codes  = hourly.get('weathercode', [])
    temps  = hourly.get('temperature_2m', [])

    waves = []
    if data.get('marine') and 'hourly' in data['marine']:
        waves = data['marine']['hourly'].get('wave_height', [])

    # Build sunrise/sunset lookup keyed by date string (YYYY-MM-DD)
    sun = {}
    for date_str, rise_str, set_str in zip(
            daily.get('time', []),
            daily.get('sunrise', []),
            daily.get('sunset',  [])):
        sun[date_str] = {
            'sunrise': datetime.fromisoformat(rise_str),
            'sunset':  datetime.fromisoformat(set_str),
        }

    now  = datetime.now()
    days = {}   # keyed by date string, preserves insertion order (Python 3.7+)

    for i, time_str in enumerate(times):
        dt       = datetime.fromisoformat(time_str)
        date_key = dt.strftime('%Y-%m-%d')

        if dt < now:
            continue

        # Only include daylight hours
        day_sun = sun.get(date_key)
        if day_sun:
            if dt < day_sun['sunrise'] or dt > day_sun['sunset']:
                continue

        spd     = round(speeds[i])   if i < len(speeds) else 0
        gust    = round(gusts[i])    if i < len(gusts)  else None
        deg     = dirs[i]            if i < len(dirs)   else 0
        compass = degrees_to_compass(deg)
        code    = codes[i]           if i < len(codes)  else 0
        temp    = round(temps[i])    if i < len(temps)  else None
        wave    = round(waves[i], 1) if i < len(waves)  else None
        rating           = rate_slot(spot, spd, compass)
        wind_in_range    = spot.min_wind <= spd <= spot.max_wind
        direction_usable = rating in ('perfect', 'good', 'okay')

        # Wind: always coloured — blue=too light, green=in range, red=too strong
        if spd < spot.min_wind:
            wind_speed_colour = '#e3f2fd'   # too light
        elif spd > spot.max_wind:
            wind_speed_colour = '#ffcccc'   # too strong
        else:
            wind_speed_colour = '#c8f7c5'   # in range

        # Direction: coloured only if perfect/good/okay, grey otherwise
        wind_dir_colour = RATING_COLOURS[rating] if direction_usable else '#f5f5f5'

        # Gusts: store raw colour — only applied if time slot is green (all_good)
        if gust is None or spd == 0:
            gust_colour_raw = '#f5f5f5'
        else:
            gust_pct = (gust - spd) / spd * 100
            if gust_pct <= 30:   gust_colour_raw = '#c8f7c5'
            elif gust_pct <= 50: gust_colour_raw = '#ffe0b2'
            else:                gust_colour_raw = '#ffcccc'

        slot = {
            'time':              dt.strftime('%H:%M'),
            'wind_speed':        spd,
            'wind_gust':         gust,
            'wind_dir':          compass,
            'wind_dir_deg':      deg,
            'emoji':             WMO_EMOJI.get(code, '🌡️'),
            'temperature':       temp,
            'wave_height':       wave,
            'rating':            rating,
            'wind_in_range':     wind_in_range,
            'direction_usable':  direction_usable,
            'wind_speed_colour': wind_speed_colour,
            'wind_dir_colour':   wind_dir_colour,
            'gust_colour_raw':   gust_colour_raw,
            'gust_colour':       '#f5f5f5',   # set after tide merge
            'header_colour':     '#f0f0f0',   # set after tide merge
            'tide_height':       None,
            'tide_pct':          None,
            'tide_colour':       '#f5f5f5',
        }

        if date_key not in days:
            sr = day_sun['sunrise'].strftime('%H:%M') if day_sun else '—'
            ss = day_sun['sunset'].strftime('%H:%M')  if day_sun else '—'
            days[date_key] = {
                'label':   dt.strftime('%A %d %b'),
                'sunrise': sr,
                'sunset':  ss,
                'slots':   [],
            }
        days[date_key]['slots'].append(slot)

    # Merge tide data
    try:
        from tides import get_tide_slots
        from models import TideCache
        target_dates = [datetime.strptime(k, '%Y-%m-%d').date() for k in days]
        tide_data = get_tide_slots(spot, target_dates)
        has_tide  = bool(tide_data)
        # tide_real = True if station found (live data), False if falling back to dummy
        from models import TideCache as TC
        tc = TC.query.filter_by(spot_id=spot.id).first()
        tide_real = bool(tc and tc.station_id)

        for date_key, day in days.items():
            for slot in day['slots']:
                hour = int(slot['time'].split(':')[0])
                td   = tide_data.get(date_key, {}).get(hour)
                if td:
                    slot['tide_height'] = td['height']
                    slot['tide_pct']    = td['pct']
                    tide_usable = spot.min_tide_percent <= td['pct'] <= spot.max_tide_percent
                else:
                    tide_usable = False

                # Time slot green only when ALL conditions are good
                all_good = (slot['wind_in_range']
                            and slot['direction_usable']
                            and tide_usable)
                slot['header_colour'] = '#4CAF50' if all_good else '#f0f0f0'

                # Gusts and tide only coloured when time slot is green
                slot['gust_colour'] = slot['gust_colour_raw'] if all_good else '#f5f5f5'
                slot['tide_colour'] = td['colour'] if (all_good and td) else '#f5f5f5'
    except Exception as e:
        print(f"[Tides] Could not merge tide data: {e}")
        has_tide  = False
        tide_real = False
        for day in days.values():
            for slot in day['slots']:
                slot['tide_height'] = None
                slot['tide_pct']    = None
                slot['tide_colour'] = '#f5f5f5'

    return list(days.values()), cache.fetched_at, has_tide, tide_real
