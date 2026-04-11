"""
Alert logic for WindChaser WhatsApp notifications.

For each user with whatsapp_enabled=True:
  - Check each "Alert Me" spot for today / tomorrow / day after
  - For each day, get the user's available slots (morning/afternoon/evening)
  - Define slot hour ranges using actual sunrise/sunset from weather cache
  - Group available slots into contiguous periods
  - Count good hours within each contiguous period
  - Alert if any contiguous period has >= 3 good hours
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from models import db, User, UserFavouriteSpot, WeatherCache, TideCache

ALERT_HOUR = 7   # Local hour at which each user receives their daily alert
from weather import (_parse_weather_cache, _tide_irrelevant,
                     _sun_hours, _slot_hours, _available_slots_for_day,
                     _contiguous_groups, _good_hours_in_set)


# ---------------------------------------------------------------------------
# Main alert computation
# ---------------------------------------------------------------------------

def get_alerts_for_user(user):
    """Return list of alert dicts for a user (spots with >= 3 contiguous good hours).

    Each dict: {spot, day_label, hours, conditions}
    """
    from tides import _parse_events, _events_to_slots

    today  = date.today()
    now    = datetime.now()
    alerts = []

    # Use whatsapp day-flags as general "which days to alert" preference.
    # If none are set (e.g. push-only users who never configured WhatsApp),
    # default to today + tomorrow so they still receive alerts.
    days_to_check = []
    if user.whatsapp_today:     days_to_check.append(0)
    if user.whatsapp_tomorrow:  days_to_check.append(1)
    if user.whatsapp_day_after: days_to_check.append(2)
    if not days_to_check:
        days_to_check = [0, 1]  # default: today and tomorrow

    favs = UserFavouriteSpot.query.filter_by(user_id=user.id, is_active=True).all()
    if not favs:
        return []

    # Pre-load weather + tide cache per spot so we can loop day-first below
    target_dates = [today + timedelta(days=i) for i in range(3)]
    spot_data = {}
    for fav in favs:
        spot    = fav.spot
        w_cache = WeatherCache.query.filter_by(spot_id=spot.id).first()
        if not w_cache or not w_cache.forecast_json:
            continue
        times, speeds, dirs, _, _, _, _, sun = _parse_weather_cache(w_cache)
        tide_irrelevant = _tide_irrelevant(spot)
        tide_data = {}
        if not tide_irrelevant:
            t_cache = TideCache.query.filter_by(spot_id=spot.id).first()
            if t_cache and t_cache.events_json:
                try:
                    tide_data = _events_to_slots(
                        _parse_events(t_cache.events_json), spot, target_dates,
                        hat=t_cache.station_hat, lat=t_cache.station_lat)
                except Exception:
                    pass
        spot_data[spot.id] = {
            'spot': spot, 'times': times, 'speeds': speeds,
            'dirs': dirs, 'sun': sun,
            'tide_data': tide_data, 'tide_irrelevant': tide_irrelevant,
        }

    # Loop day-first so the message reads Today → Tomorrow → Day after
    for offset in days_to_check:
        target    = today + timedelta(days=offset)
        date_key  = target.isoformat()
        available = _available_slots_for_day(user, target.weekday())
        if not available:
            continue

        if offset == 0:   day_label = 'Today'
        elif offset == 1: day_label = 'Tomorrow'
        else:             day_label = target.strftime('%A')

        for sd in spot_data.values():
            spot            = sd['spot']
            sunrise_h, sunset_h = _sun_hours(date_key, sd['sun'])
            groups          = _contiguous_groups(available, sunrise_h, sunset_h)

            best_hours, best_conditions, best_start = 0, '', None
            for hour_set in groups:
                if not hour_set:
                    continue
                count, cond, start_h = _good_hours_in_set(
                    hour_set, date_key, spot, user,
                    sd['times'], sd['speeds'], sd['dirs'],
                    sd['tide_data'], sd['tide_irrelevant'], now)
                if count > best_hours:
                    best_hours, best_conditions, best_start = count, cond, start_h

            if best_hours >= 3:
                alerts.append({
                    'spot':       spot,
                    'day_label':  day_label,
                    'hours':      best_hours,
                    'conditions': best_conditions,
                    'start_hour': best_start,
                })

    return alerts


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

def build_alert_message(alerts, app_url=''):
    """Format the WhatsApp message. Returns None if no alerts."""
    if not alerts:
        return None

    # Group alerts by day label preserving order
    days_seen = []
    by_day = {}
    for a in alerts:
        lbl = a['day_label']
        if lbl not in by_day:
            days_seen.append(lbl)
            by_day[lbl] = []
        by_day[lbl].append(a)

    lines = ['🪁 *WindChaser* – your conditions update\n']
    for lbl in days_seen:
        lines.append(f"*{lbl}*")
        for a in by_day[lbl]:
            hrs   = a['hours']
            parts = []
            if a['conditions']:
                parts.append(f"Wind: {a['conditions']}")
            start = a.get('start_hour')
            if start is not None:
                suffix = 'am' if start < 12 else 'pm'
                hour12 = start if 1 <= start <= 12 else (start - 12 if start > 12 else 12)
                parts.append(f"{hrs} good hour{'s' if hrs != 1 else ''} starting at {hour12}{suffix}")
            else:
                parts.append(f"{hrs} good hour{'s' if hrs != 1 else ''}")
            lines.append(f"• {a['spot'].name} – {' · '.join(parts)}")
        lines.append('')

    if app_url:
        lines.append(f"🔗 {app_url}")

    return '\n'.join(lines).strip()


# ---------------------------------------------------------------------------
# Email alert sender
# ---------------------------------------------------------------------------

def send_alert_email(user, alerts, app_url=''):
    """Send the conditions alert as an email. Returns (ok: bool, detail: str)."""
    try:
        from app import mail
        from flask_mail import Message as MailMessage

        days_seen, by_day = [], {}
        for a in alerts:
            lbl = a['day_label']
            if lbl not in by_day:
                days_seen.append(lbl)
                by_day[lbl] = []
            by_day[lbl].append(a)

        # Build HTML body
        rows = ''
        for lbl in days_seen:
            rows += f'<h3 style="margin:16px 0 6px;">{lbl}</h3>'
            for a in by_day[lbl]:
                hrs   = a['hours']
                start = a.get('start_hour')
                parts = []
                if a['conditions']:
                    parts.append(f"Wind: {a['conditions']}")
                if start is not None:
                    suffix = 'am' if start < 12 else 'pm'
                    h12 = start if 1 <= start <= 12 else (start - 12 if start > 12 else 12)
                    parts.append(f"{hrs} good hour{'s' if hrs != 1 else ''} from {h12}{suffix}")
                else:
                    parts.append(f"{hrs} good hour{'s' if hrs != 1 else ''}")
                rows += (f'<p style="margin:4px 0;">🪁 <strong>{a["spot"].name}</strong> — '
                         f'{" · ".join(parts)}</p>')

        base_url = app_url.rstrip('/') if app_url else ''
        icon_url = f'{base_url}/static/icon-192.png' if base_url else ''
        icon_img = (f'<img src="{icon_url}" width="40" height="40" '
                    f'style="vertical-align:middle;border-radius:10px;margin-right:10px;">'
                    if icon_url else '')
        link = f'<p style="margin-top:20px;"><a href="{app_url}">Open WindChaser</a></p>' if app_url else ''
        html = f"""
<div style="font-family:sans-serif;max-width:520px;">
  <h2 style="color:#0d6efd;">{icon_img}WindChaser — conditions update</h2>
  {rows}
  {link}
</div>"""

        msg = MailMessage(
            subject='WindChaser — good kiting conditions coming up!',
            recipients=[user.email],
            html=html,
        )
        mail.send(msg)
        return True, 'sent'
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Send for one user
# ---------------------------------------------------------------------------

def send_alerts_for_user(user, app_url=''):
    """Compute and send alerts for one user via their chosen notification channel(s).

    Returns (sent: bool, detail: str).
    'both' = push app notification + email.
    """
    ntype = user.notification_type or 'none'
    if ntype == 'none':
        return False, 'Notifications disabled'

    alerts  = get_alerts_for_user(user)
    if not alerts:
        return False, 'No qualifying conditions to report'

    results = []

    if ntype in ('push', 'both'):
        message = build_alert_message(alerts, app_url)
        from push import send_push_to_user
        ok, detail = send_push_to_user(
            user,
            '🪁 WindChaser – conditions update',
            message,
            app_url
        )
        results.append(f"Push: {'sent' if ok else detail}")

    if ntype in ('email', 'both'):
        ok, detail = send_alert_email(user, alerts, app_url)
        results.append(f"Email: {'sent' if ok else detail}")

    sent = any('sent' in r for r in results)
    return sent, ' | '.join(results)


# ---------------------------------------------------------------------------
# Send for all enabled users (called by scheduler or admin trigger)
# ---------------------------------------------------------------------------

def send_all_alerts(app_url=''):
    """Send alerts to every user who has notifications enabled.

    Returns list of (user, sent, detail) tuples.
    """
    users = User.query.filter(
        User.is_active == True,
        User.notification_type.isnot(None),
        User.notification_type != 'none'
    ).all()
    results = []
    for user in users:
        sent, detail = send_alerts_for_user(user, app_url)
        results.append((user, sent, detail))
    return results


def send_due_alerts(app_url=''):
    """Send alerts only to users for whom it is currently ALERT_HOUR in their timezone.

    Called by the hourly cron job so each user receives their alert at
    the same local time regardless of where in the world they are.
    Returns list of (user, sent, detail) tuples.
    """
    now_utc = datetime.now(timezone.utc)

    users = User.query.filter(
        User.is_active == True,
        User.notification_type.isnot(None),
        User.notification_type != 'none'
    ).all()

    results = []
    for user in users:
        tz_name = user.timezone or 'Europe/London'
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo('Europe/London')

        local_hour = now_utc.astimezone(tz).hour
        if local_hour != ALERT_HOUR:
            continue

        print(f"[Alerts] Sending due alert to {user.email} (local hour={local_hour} in {tz_name})")
        try:
            sent, detail = send_alerts_for_user(user, app_url)
            if sent:
                log_event('CRON', 'alert_sent',
                          detail=f"{user.email} — {detail}",
                          user_id=user.id)
            else:
                log_event('CRON', 'alert_skipped',
                          detail=f"{user.email} — {detail}",
                          user_id=user.id)
            results.append((user, sent, detail))
        except Exception as e:
            log_event('CRON', 'alert_failed',
                      detail=f"{user.email} — {e}",
                      user_id=user.id)
            results.append((user, False, str(e)))

    from log_utils import purge_old_logs
    purge_old_logs()

    return results
