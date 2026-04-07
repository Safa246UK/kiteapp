import requests
import json
from datetime import datetime, date, timedelta
from models import db, WeatherCache, TideCache

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
    'perfect':     '#c8f7c5',   # light green
    'good':        '#FFE0B2',   # light orange
    'poor':        '#FCE4EC',   # light pink
    'dangerous':   '#E0E0E0',   # dark grey
    'out_of_range':'#f5f5f5',
}

COLOUR_HEX = {'green': '#4CAF50', 'amber': '#FFD54F', 'grey': '#e0e0e0'}


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def degrees_to_compass(deg):
    return COMPASS[round(deg / 22.5) % 16]


def _direction_rating(spot, wind_dir_compass):
    """Return direction rating for a compass point, ignoring wind speed."""
    def dirs(field):
        v = getattr(spot, field, '') or ''
        return [d.strip() for d in v.split(',') if d.strip()]

    if wind_dir_compass in dirs('perfect_directions'):   return 'perfect'
    if wind_dir_compass in dirs('good_directions'):      return 'good'
    if wind_dir_compass in dirs('poor_directions'):      return 'poor'
    # okay_directions are treated as dangerous (legacy field, no longer used)
    return 'dangerous'


def rate_slot(spot, wind_speed, wind_dir_compass, min_wind, max_wind):
    """Return a rating string for one time slot."""
    if wind_speed < min_wind or wind_speed > max_wind:
        return 'out_of_range'
    return _direction_rating(spot, wind_dir_compass)


def _tide_irrelevant(spot):
    """True if tide should be ignored — landlocked OR no station within range."""
    if spot.is_landlocked:
        return True
    tc = TideCache.query.filter_by(spot_id=spot.id).first()
    return tc is not None and not tc.station_id


# ---------------------------------------------------------------------------
# Availability + slot-hour helpers (shared with alerts.py)
# ---------------------------------------------------------------------------

def _sun_hours(date_key, sun):
    """Return (sunrise_hour, sunset_hour) integers for a date, with fallback."""
    day = sun.get(date_key)
    if not day:
        return 6, 21
    return day['sunrise'].hour, day['sunset'].hour


def _slot_hours(slot, sunrise_h, sunset_h):
    """Return set of integer hours covered by the named slot on this day."""
    if slot == 'morning':
        return set(range(max(sunrise_h, 0), 12))
    if slot == 'afternoon':
        return set(range(12, min(18, sunset_h)))
    if slot == 'evening':
        return set(range(18, sunset_h)) if sunset_h > 18 else set()
    return set()


def _available_slots_for_day(user, day_of_week):
    """Return set of slot names the user is available for on this weekday (0=Mon)."""
    day_key = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[day_of_week]
    if not user.available_slots:
        return set()
    return {
        s[len(day_key) + 1:]
        for s in user.available_slots.split(',')
        if s.strip().startswith(day_key + '_')
    }


def _contiguous_groups(available_slots, sunrise_h, sunset_h):
    """Return list of hour-sets, one per maximal contiguous run of available slots.

    morning/afternoon are always contiguous (share 12:00).
    afternoon/evening are contiguous only when sunset > 18:00.
    """
    ordered = [s for s in ('morning', 'afternoon', 'evening') if s in available_slots]
    if not ordered:
        return []

    def adjacent(a, b):
        if a == 'morning'   and b == 'afternoon': return True
        if a == 'afternoon' and b == 'evening':   return sunset_h > 18
        return False

    groups, current = [], [ordered[0]]
    for i in range(1, len(ordered)):
        if adjacent(ordered[i - 1], ordered[i]):
            current.append(ordered[i])
        else:
            groups.append(current)
            current = [ordered[i]]
    groups.append(current)

    return [
        {h for slot in g for h in _slot_hours(slot, sunrise_h, sunset_h)}
        for g in groups
    ]


def _good_hours_in_set(hour_set, date_key, spot, user,
                       times, speeds, dirs, tide_data, tide_irrelevant, now):
    """Count good hours within hour_set for the given date.

    Returns (count, conditions_str, start_hour) where start_hour is the
    first hour (int) with good conditions, or None if none found.
    """
    good_speeds, good_dirs, good_hours = [], [], []

    for i, time_str in enumerate(times):
        dt = datetime.fromisoformat(time_str)
        if dt.strftime('%Y-%m-%d') != date_key or dt < now or dt.hour not in hour_set:
            continue
        spd     = round(speeds[i]) if i < len(speeds) else 0
        compass = degrees_to_compass(dirs[i] if i < len(dirs) else 0)
        wind_ok = user.min_wind <= spd <= user.max_wind
        dir_ok  = _direction_rating(spot, compass) in ('perfect', 'good', 'okay')
        td      = tide_data.get(date_key, {}).get(dt.hour)
        tide_ok = bool(td and spot.min_tide_percent <= td['pct'] <= spot.max_tide_percent)
        if wind_ok and dir_ok and (tide_ok or tide_irrelevant):
            good_speeds.append(spd)
            good_dirs.append(compass)
            good_hours.append(dt.hour)

    if not good_speeds:
        return 0, '', None
    avg_spd  = round(sum(good_speeds) / len(good_speeds))
    dir_freq = {}
    for d in good_dirs:
        dir_freq[d] = dir_freq.get(d, 0) + 1
    top_dir    = max(dir_freq, key=dir_freq.get)
    start_hour = min(good_hours)
    return len(good_speeds), f"{avg_spd}kn {top_dir}", start_hour


# ---------------------------------------------------------------------------
# Shared parsing helpers (eliminate duplication across the three summary paths)
# ---------------------------------------------------------------------------

def _parse_weather_cache(cache):
    """Unpack a WeatherCache row into the arrays used by all forecast functions.

    Returns: (times, speeds, dirs, gusts, codes, temps, waves, sun)
    """
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

    sun = {}
    for date_str, rise_str, set_str in zip(
            daily.get('time', []),
            daily.get('sunrise', []),
            daily.get('sunset',  [])):
        sun[date_str] = {
            'sunrise': datetime.fromisoformat(rise_str),
            'sunset':  datetime.fromisoformat(set_str),
        }

    return times, speeds, dirs, gusts, codes, temps, waves, sun


def _count_good_hours(spot, times, speeds, dirs, sun,
                      tide_data, tide_irrelevant, min_wind, max_wind, target_dates):
    """Count daylight hours that meet wind + direction + tide criteria.

    Returns a dict keyed by ISO date string.
    """
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

        wind_in_range    = min_wind <= spd <= max_wind
        direction_usable = _direction_rating(spot, compass) in ('perfect', 'good', 'okay')
        td               = tide_data.get(date_key, {}).get(dt.hour)
        tide_usable      = bool(td and spot.min_tide_percent <= td['pct'] <= spot.max_tide_percent)

        if wind_in_range and direction_usable and (tide_usable or tide_irrelevant):
            day_counts[date_key] += 1

    return day_counts


# ---------------------------------------------------------------------------
# Weather fetching
# ---------------------------------------------------------------------------

def fetch_and_cache_weather(spot):
    """Call Open-Meteo (+ marine) and store result in WeatherCache."""
    weather_resp = requests.get(WEATHER_API, params={
        'latitude':        spot.latitude,
        'longitude':       spot.longitude,
        'hourly':          'windspeed_10m,winddirection_10m,windgusts_10m,weathercode,temperature_2m',
        'daily':           'sunrise,sunset',
        'wind_speed_unit': 'kn',
        'timezone':        'Europe/London',
        'forecast_days':   7,
    }, timeout=10)
    weather_data = weather_resp.json()

    marine_data = None
    try:
        marine_resp = requests.get(MARINE_API, params={
            'latitude':      spot.latitude,
            'longitude':     spot.longitude,
            'hourly':        'wave_height',
            'timezone':      'Europe/London',
            'forecast_days': 7,
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


# ---------------------------------------------------------------------------
# Full forecast table (used by spot detail page)
# ---------------------------------------------------------------------------

def get_forecast_table(spot, user=None):
    """Return (days, fetched_at, has_tide, tide_real).

    Uses the user's personal wind settings when provided.
    Returns (None, None, False, False) if no cache exists yet.
    """
    cache = WeatherCache.query.filter_by(spot_id=spot.id).first()
    if not cache:
        return None, None, False, False

    eff_min_wind = user.min_wind if user else 12.0
    eff_max_wind = user.max_wind if user else 35.0

    times, speeds, dirs, gusts, codes, temps, waves, sun = _parse_weather_cache(cache)

    now  = datetime.now()
    days = {}

    for i, time_str in enumerate(times):
        dt       = datetime.fromisoformat(time_str)
        date_key = dt.strftime('%Y-%m-%d')

        if dt < now:
            continue

        day_sun = sun.get(date_key)
        if day_sun and (dt < day_sun['sunrise'] or dt > day_sun['sunset']):
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
        direction_usable = dir_rating in ('perfect', 'good')

        # Wind speed: always coloured
        if spd < eff_min_wind:
            wind_speed_colour = '#e3f2fd'
        elif spd > eff_max_wind:
            wind_speed_colour = '#ffcccc'
        else:
            wind_speed_colour = '#c8f7c5'

        # Direction: always coloured by its own rating
        wind_dir_colour = RATING_COLOURS.get(dir_rating, '#f5f5f5')

        # Availability: is this hour in the user's "Times I can kite" slots?
        available = False
        if user and user.available_slots:
            day_of_week  = dt.weekday()        # 0=Mon, 6=Sun
            sr_h = day_sun['sunrise'].hour if day_sun else 6
            # Use ceiling for sunset: if sunset is 19:50 the 19h slot is still usable
            _sd  = day_sun['sunset'] if day_sun else None
            ss_h = (_sd.hour + (1 if _sd.minute > 0 else 0)) if _sd else 21
            for slot_period in _available_slots_for_day(user, day_of_week):
                if dt.hour in _slot_hours(slot_period, sr_h, ss_h):
                    available = True
                    break

        # Gusts: raw colour applied later only if slot is green
        if gust is None:
            gust_colour_raw = '#f5f5f5'
        elif spd == 0:
            gust_colour_raw = '#c8f7c5'  # wind is calm so gusts are fine; avoid divide-by-zero
        else:
            gust_pct = (gust - spd) / spd * 100
            if gust_pct <= 30:   gust_colour_raw = '#c8f7c5'
            elif gust_pct <= 50: gust_colour_raw = '#ffe0b2'
            else:                gust_colour_raw = '#ffcccc'

        slot = {
            'time':              dt.strftime('%Hh'),
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
            'gust_colour':       '#f5f5f5',
            'header_colour':     '#f0f0f0',
            'tide_height':       None,
            'tide_pct':          None,
            'tide_colour':       '#f5f5f5',
            'available':         available,
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
        tide_irrelevant = _tide_irrelevant(spot)
        if tide_irrelevant:
            tide_data = {}
            has_tide  = False
        else:
            from tides import get_tide_slots
            target_dates = [datetime.strptime(k, '%Y-%m-%d').date() for k in days]
            tide_data = get_tide_slots(spot, target_dates)
            has_tide  = bool(tide_data)

        tc        = TideCache.query.filter_by(spot_id=spot.id).first()
        tide_real = bool(tc and tc.station_id)

        for date_key, day in days.items():
            for slot in day['slots']:
                hour = int(slot['time'].rstrip('h').split(':')[0])
                td   = tide_data.get(date_key, {}).get(hour)
                if td:
                    slot['tide_height'] = td['height']
                    slot['tide_pct']    = td['pct']
                    tide_usable = spot.min_tide_percent <= td['pct'] <= spot.max_tide_percent
                else:
                    tide_usable = False

                all_good = (slot['wind_in_range']
                            and slot['direction_usable']
                            and (tide_usable or tide_irrelevant))
                slot['header_colour'] = '#4CAF50' if all_good else '#f0f0f0'
                # Each row always shows its own colour so the user can see why a slot isn't good
                slot['gust_colour'] = slot['gust_colour_raw']
                slot['tide_colour'] = td['colour'] if td else '#f5f5f5'

    except Exception as e:
        print(f"[Tides] Could not merge tide data: {e}")
        has_tide  = False
        tide_real = False
        for day in days.values():
            for slot in day['slots']:
                slot['tide_height'] = None
                slot['tide_pct']    = None
                slot['tide_colour'] = '#f5f5f5'

    _save_day_summary(spot, days)
    return list(days.values()), cache.fetched_at, has_tide, tide_real


# ---------------------------------------------------------------------------
# Day summary helpers (dashboard squares)
# ---------------------------------------------------------------------------

def _save_day_summary(spot, days):
    """Persist green/amber/grey counts to WeatherCache.day_summary_json."""
    summary = {}
    for date_key, day in days.items():
        good_hours = sum(1 for s in day['slots'] if s['header_colour'] == '#4CAF50')
        colour = 'green' if good_hours >= 3 else ('amber' if good_hours >= 1 else 'grey')
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
    """Standalone summary using spot-level wind settings.

    Called at startup, hourly by the scheduler, and on spot creation.
    Does not depend on get_forecast_table.
    """
    cache = WeatherCache.query.filter_by(spot_id=spot.id).first()
    if not cache or not cache.forecast_json:
        print(f"[Summaries] No weather cache yet for {spot.name} — skipping")
        return

    times, speeds, dirs, _, _, _, _, sun = _parse_weather_cache(cache)
    target_dates    = [date.today() + timedelta(days=i) for i in range(3)]
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

    day_counts = _count_good_hours(
        spot, times, speeds, dirs, sun,
        tide_data, tide_irrelevant,
        12.0, 35.0, target_dates,
    )

    summary = {
        d.isoformat(): {
            'colour': 'green' if day_counts[d.isoformat()] >= 3
                      else ('amber' if day_counts[d.isoformat()] >= 1 else 'grey'),
            'hours':  day_counts[d.isoformat()],
        }
        for d in target_dates
    }

    try:
        cache.day_summary_json = json.dumps(summary)
        db.session.commit()
        print(f"[Summaries] Saved for {spot.name}: "
              f"{[(k, v['colour'], v['hours']) for k, v in summary.items()]}")
    except Exception as e:
        db.session.rollback()
        print(f"[Summaries] DB save failed for {spot.name}: {e}")


def get_day_summaries_for_user(spot_id, user):
    """Compute day summaries using the user's availability and wind settings.

    Green  = any contiguous available period has >= 3 good hours.
    Amber  = any contiguous available period has >= 1 good hour.
    Grey   = no good hours within available periods.
    """
    from tides import _parse_events, _events_to_slots
    from models import Spot

    spot    = Spot.query.get(spot_id)
    w_cache = WeatherCache.query.filter_by(spot_id=spot_id).first()
    if not spot or not w_cache or not w_cache.forecast_json:
        return [{'label': lbl, 'colour': COLOUR_HEX['grey'], 'hours': None}
                for lbl in ('Today', 'Tomorrow', 'The next day')]

    times, speeds, dirs, _, _, _, _, sun = _parse_weather_cache(w_cache)
    target_dates    = [date.today() + timedelta(days=i) for i in range(3)]
    tide_irrelevant = _tide_irrelevant(spot)
    tide_data       = {}
    now             = datetime.now()

    if not tide_irrelevant:
        t_cache = TideCache.query.filter_by(spot_id=spot_id).first()
        if t_cache and t_cache.events_json:
            try:
                tide_data = _events_to_slots(
                    _parse_events(t_cache.events_json), spot, target_dates,
                    hat=t_cache.station_hat, lat=t_cache.station_lat)
            except Exception:
                pass

    result = []
    for i, label in enumerate(('Today', 'Tomorrow', 'The next day')):
        target    = target_dates[i]
        date_key  = target.isoformat()
        available = _available_slots_for_day(user, target.weekday())

        if not available:
            result.append({'label': label, 'colour': COLOUR_HEX['grey'], 'hours': None})
            continue

        sunrise_h, sunset_h = _sun_hours(date_key, sun)
        groups      = _contiguous_groups(available, sunrise_h, sunset_h)
        best_hours  = 0
        for hour_set in groups:
            if not hour_set:
                continue
            count, _, _sh = _good_hours_in_set(
                hour_set, date_key, spot, user,
                times, speeds, dirs, tide_data, tide_irrelevant, now)
            if count > best_hours:
                best_hours = count

        colour = 'green' if best_hours >= 3 else ('amber' if best_hours >= 1 else 'grey')
        result.append({'label': label, 'colour': COLOUR_HEX[colour], 'hours': best_hours})
    return result
