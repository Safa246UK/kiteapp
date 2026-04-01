import requests
import json
import os
from datetime import datetime, date, timedelta
from models import db, WeatherCache


def _tide_irrelevant(spot):
    """True if tide should be ignored — landlocked OR no station within range."""
    if spot.is_landlocked:
        return True
    from models import TideCache
    tc = TideCache.query.filter_by(spot_id=spot.id).first()
    return tc is not None and not tc.station_id

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


def _direction_rating(spot, wind_dir_compass):
    """Return direction rating for a compass point, ignoring wind speed."""
    def dirs(field):
        v = getattr(spot, field, '') or ''
        return [d.strip() for d in v.split(',') if d.strip()]

    if wind_dir_compass in dirs('perfect_directions'):   return 'perfect'
    if wind_dir_compass in dirs('good_directions'):      return 'good'
    if wind_dir_compass in dirs('okay_directions'):      return 'okay'
    if wind_dir_compass in dirs('poor_directions'):      return 'poor'
    return 'dangerous'


def rate_slot(spot, wind_speed, wind_dir_compass):
    """Return a rating string for one time slot (uses spot wind range)."""
    if wind_speed < spot.min_wind or wind_speed > spot.max_wind:
        return 'out_of_range'
    return _direction_rating(spot, wind_dir_compass)


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


def get_forecast_table(spot, user=None):
    """
    Return (days, fetched_at, has_tide, tide_real).
    If user is provided, their personal wind settings are used for colour coding.
    Returns (None, None, False, False) if no cache exists yet.
    """
    cache = WeatherCache.query.filter_by(spot_id=spot.id).first()
    if not cache:
        return None, None, False, False

    eff_min_wind = user.min_wind if user else spot.min_wind
    eff_max_wind = user.max_wind if user else spot.max_wind

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
        wave    = round(waves[i], 1) if (i < len(waves) and waves[i] is not None) else None
        dir_rating       = _direction_rating(spot, compass)
        wind_in_range    = eff_min_wind <= spd <= eff_max_wind
        direction_usable = dir_rating in ('perfect', 'good', 'okay')

        # Wind: always coloured — blue=too light, green=in range, red=too strong
        if spd < eff_min_wind:
            wind_speed_colour = '#e3f2fd'   # too light
        elif spd > eff_max_wind:
            wind_speed_colour = '#ffcccc'   # too strong
        else:
            wind_speed_colour = '#c8f7c5'   # in range

        # Direction: coloured only if wind is in range AND direction is perfect/good/okay
        wind_dir_colour = RATING_COLOURS[dir_rating] if (wind_in_range and direction_usable) else '#f5f5f5'

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
            'rating':            dir_rating,
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

    # Merge tide data (skip for landlocked spots or spots with no nearby station)
    try:
        tide_irrelevant = _tide_irrelevant(spot)
        if tide_irrelevant:
            tide_data = {}
            has_tide  = False
        else:
            from tides import get_tide_slots
            target_dates = [datetime.strptime(k, '%Y-%m-%d').date() for k in days]
            tide_data = get_tide_slots(spot, target_dates)
            has_tide  = bool(tide_data)
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
                # Tide ignored for landlocked spots or spots with no nearby tidal station
                all_good = (slot['wind_in_range']
                            and slot['direction_usable']
                            and (tide_usable or tide_irrelevant))
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

    # Keep summary fresh after every detail page visit
    _save_day_summary(spot, days)

    return list(days.values()), cache.fetched_at, has_tide, tide_real


def _save_day_summary(spot, days):
    """Persist green/amber/grey counts to WeatherCache.day_summary_json."""
    summary = {}
    for date_key, day in days.items():
        good_hours = sum(1 for s in day['slots'] if s['header_colour'] == '#4CAF50')
        if good_hours >= 3:
            colour = 'green'
        elif good_hours >= 1:
            colour = 'amber'
        else:
            colour = 'grey'
        summary[date_key] = {'colour': colour, 'hours': good_hours}
    try:
        cache = WeatherCache.query.filter_by(spot_id=spot.id).first()
        if cache:
            cache.day_summary_json = json.dumps(summary)
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[Summaries] DB save failed for {spot.name}: {e}")


def compute_and_cache_summary(spot):
    """Standalone summary computation — called at startup, hourly, and on spot creation.
    Reads cached weather + fetches live tides. No dependency on get_forecast_table."""
    cache = WeatherCache.query.filter_by(spot_id=spot.id).first()
    if not cache or not cache.forecast_json:
        print(f"[Summaries] No weather cache yet for {spot.name} — skipping")
        return

    data   = json.loads(cache.forecast_json)
    hourly = data['weather'].get('hourly', {})
    daily  = data['weather'].get('daily',  {})

    times  = hourly.get('time', [])
    speeds = hourly.get('windspeed_10m', [])
    dirs   = hourly.get('winddirection_10m', [])

    sun = {}
    for date_str, rise_str, set_str in zip(
            daily.get('time', []),
            daily.get('sunrise', []),
            daily.get('sunset',  [])):
        sun[date_str] = {
            'sunrise': datetime.fromisoformat(rise_str),
            'sunset':  datetime.fromisoformat(set_str),
        }

    target_dates = [date.today() + timedelta(days=i) for i in range(3)]

    tide_irrelevant = _tide_irrelevant(spot)
    try:
        if tide_irrelevant:
            tide_data = {}
        else:
            from tides import get_tide_slots
            tide_data = get_tide_slots(spot, target_dates)
    except Exception as e:
        print(f"[Summaries] Tide fetch failed for {spot.name}: {e}")
        tide_data = {}

    now = datetime.now()
    day_counts = {d.isoformat(): 0 for d in target_dates}

    for i, time_str in enumerate(times):
        dt       = datetime.fromisoformat(time_str)
        date_key = dt.strftime('%Y-%m-%d')

        if date_key not in day_counts or dt < now:
            continue

        day_sun = sun.get(date_key)
        if day_sun and (dt < day_sun['sunrise'] or dt > day_sun['sunset']):
            continue

        spd     = round(speeds[i]) if i < len(speeds) else 0
        deg     = dirs[i]          if i < len(dirs)   else 0
        compass = degrees_to_compass(deg)
        rating  = rate_slot(spot, spd, compass)

        wind_in_range    = spot.min_wind <= spd <= spot.max_wind
        direction_usable = rating in ('perfect', 'good', 'okay')

        td          = tide_data.get(date_key, {}).get(dt.hour)
        tide_usable = bool(td and spot.min_tide_percent <= td['pct'] <= spot.max_tide_percent)

        if wind_in_range and direction_usable and (tide_usable or tide_irrelevant):
            day_counts[date_key] += 1

    summary = {}
    for d in target_dates:
        key   = d.isoformat()
        hours = day_counts[key]
        summary[key] = {
            'colour': 'green' if hours >= 3 else ('amber' if hours >= 1 else 'grey'),
            'hours':  hours,
        }

    try:
        cache.day_summary_json = json.dumps(summary)
        db.session.commit()
        print(f"[Summaries] Saved for {spot.name}: {[(k, v['colour'], v['hours']) for k, v in summary.items()]}")
    except Exception as e:
        db.session.rollback()
        print(f"[Summaries] DB save failed for {spot.name}: {e}")


def get_day_summaries_for_user(spot_id, user):
    """Compute green/amber/grey day summaries for a specific user, using their
    personal wind settings. Reads from cached weather + cached tide events — no API calls."""
    from tides import _parse_events, _events_to_slots
    from models import TideCache, Spot

    COLOUR_HEX = {'green': '#4CAF50', 'amber': '#FFD54F', 'grey': '#e0e0e0'}

    spot    = Spot.query.get(spot_id)
    w_cache = WeatherCache.query.filter_by(spot_id=spot_id).first()
    if not spot or not w_cache or not w_cache.forecast_json:
        return [{'label': lbl, 'colour': '#e0e0e0', 'hours': None}
                for lbl in ('Today', 'Tomorrow', 'The next day')]

    data   = json.loads(w_cache.forecast_json)
    hourly = data['weather'].get('hourly', {})
    daily  = data['weather'].get('daily',  {})
    times  = hourly.get('time', [])
    speeds = hourly.get('windspeed_10m', [])
    dirs   = hourly.get('winddirection_10m', [])

    sun = {}
    for date_str, rise_str, set_str in zip(
            daily.get('time', []),
            daily.get('sunrise', []),
            daily.get('sunset',  [])):
        sun[date_str] = {
            'sunrise': datetime.fromisoformat(rise_str),
            'sunset':  datetime.fromisoformat(set_str),
        }

    # Use cached tide events — no live API call (skip for landlocked spots)
    target_dates    = [date.today() + timedelta(days=i) for i in range(3)]
    tide_irrelevant = _tide_irrelevant(spot)
    tide_data       = {}
    if not tide_irrelevant:
        t_cache = TideCache.query.filter_by(spot_id=spot_id).first()
        if t_cache and t_cache.events_json:
            try:
                tide_data = _events_to_slots(_parse_events(t_cache.events_json), spot, target_dates)
            except Exception:
                pass

    eff_min    = user.min_wind
    eff_max    = user.max_wind
    now        = datetime.now()
    day_counts = {d.isoformat(): 0 for d in target_dates}

    for i, time_str in enumerate(times):
        dt       = datetime.fromisoformat(time_str)
        date_key = dt.strftime('%Y-%m-%d')
        if date_key not in day_counts or dt < now:
            continue
        day_sun = sun.get(date_key)
        if day_sun and (dt < day_sun['sunrise'] or dt > day_sun['sunset']):
            continue

        spd     = round(speeds[i]) if i < len(speeds) else 0
        deg     = dirs[i]          if i < len(dirs)   else 0
        compass = degrees_to_compass(deg)

        wind_in_range    = eff_min <= spd <= eff_max
        direction_usable = _direction_rating(spot, compass) in ('perfect', 'good', 'okay')
        td               = tide_data.get(date_key, {}).get(dt.hour)
        tide_usable      = bool(td and spot.min_tide_percent <= td['pct'] <= spot.max_tide_percent)

        if wind_in_range and direction_usable and (tide_usable or tide_irrelevant):
            day_counts[date_key] += 1

    result = []
    for i, label in enumerate(('Today', 'Tomorrow', 'The next day')):
        key    = (date.today() + timedelta(days=i)).isoformat()
        hours  = day_counts.get(key, 0)
        colour = 'green' if hours >= 3 else ('amber' if hours >= 1 else 'grey')
        result.append({'label': label, 'colour': COLOUR_HEX[colour], 'hours': hours})
    return result


def get_day_summaries(spot_id):
    """Return a list of 3 dicts [{label, colour, hours}] for Today/Tomorrow/The next day.
    Reads from cached day_summary_json — no API calls."""
    COLOUR_HEX = {'green': '#4CAF50', 'amber': '#FFD54F', 'grey': '#e0e0e0'}

    cache = WeatherCache.query.filter_by(spot_id=spot_id).first()
    stored = {}
    if cache and cache.day_summary_json:
        try:
            stored = json.loads(cache.day_summary_json)
        except Exception:
            pass

    today = date.today()
    result = []
    for i, label in enumerate(('Today', 'Tomorrow', 'The next day')):
        key   = (today + timedelta(days=i)).isoformat()
        entry = stored.get(key)
        if entry:
            result.append({
                'label':  label,
                'colour': COLOUR_HEX.get(entry['colour'], '#e0e0e0'),
                'hours':  entry['hours'],
            })
        else:
            result.append({'label': label, 'colour': '#e0e0e0', 'hours': None})
    return result
