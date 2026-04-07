import threading
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from models import db, UserFavouriteSpot, Spot, WeatherCache, AdminSettings
from weather import get_day_summaries_for_user, fetch_and_cache_weather, compute_and_cache_summary

main = Blueprint('main', __name__)

WEATHER_STALE_HOURS = 1  # Refresh weather if older than this


def _is_stale(spot_id):
    """Return True if this spot's weather cache is missing or older than WEATHER_STALE_HOURS."""
    cache = WeatherCache.query.filter_by(spot_id=spot_id).first()
    if not cache or not cache.fetched_at:
        return True
    # Also treat cache with no usable hourly data as stale
    import json
    try:
        d = json.loads(cache.forecast_json or '{}')
        if not d.get('weather', {}).get('hourly', {}).get('time'):
            return True
    except Exception:
        return True
    return cache.fetched_at < datetime.utcnow() - timedelta(hours=WEATHER_STALE_HOURS)


def _refresh_spots_background(spot_ids, app):
    """Fetch weather + recompute summaries for a list of spot IDs in a background thread."""
    with app.app_context():
        for spot_id in spot_ids:
            spot = Spot.query.get(spot_id)
            if not spot:
                continue
            try:
                fetch_and_cache_weather(spot)
                compute_and_cache_summary(spot)
                print(f"[BG Refresh] Updated: {spot.name}")
            except Exception as e:
                print(f"[BG Refresh] Failed for {spot.name}: {e}")


@main.route('/')
@login_required
def index():
    from flask import current_app
    settings    = AdminSettings.query.first()
    max_favs    = settings.max_favourite_spots if settings else 3
    max_active  = settings.max_active_spots    if settings else 2

    # Get user's favourites for non-disabled spots only
    user_favs = (UserFavouriteSpot.query
                 .filter_by(user_id=current_user.id)
                 .join(Spot)
                 .filter(Spot.is_retired == False)
                 .all())

    active_favs  = sorted([f for f in user_favs if f.is_active],     key=lambda f: f.spot.name)
    other_favs   = sorted([f for f in user_favs if not f.is_active], key=lambda f: f.spot.name)
    fav_count    = len(user_favs)
    active_count = len(active_favs)

    # --- Priority refresh: update the user's own spots synchronously so their
    #     cards are always fresh, then refresh remaining spots in the background ---
    user_spot_ids = {f.spot_id for f in user_favs}
    stale_user_spots = [sid for sid in user_spot_ids if _is_stale(sid)]

    if stale_user_spots:
        for spot_id in stale_user_spots:
            spot = Spot.query.get(spot_id)
            if spot:
                try:
                    fetch_and_cache_weather(spot)
                    compute_and_cache_summary(spot)
                    print(f"[Dashboard] Priority refresh: {spot.name}")
                except Exception as e:
                    print(f"[Dashboard] Priority refresh failed for {spot.name}: {e}")

        # Refresh all other spots in the background (don't block the page)
        other_spot_ids = [
            s.id for s in Spot.query.filter_by(is_retired=False).all()
            if s.id not in user_spot_ids and _is_stale(s.id)
        ]
        if other_spot_ids:
            app = current_app._get_current_object()
            t = threading.Thread(
                target=_refresh_spots_background,
                args=(other_spot_ids, app),
                daemon=True,
            )
            t.start()

    spot_summaries = {f.spot_id: get_day_summaries_for_user(f.spot_id, current_user) for f in user_favs}

    # Server-set cookie written by /push/subscribe — tells us this device has
    # already granted push permission so we don't need to show the prompt again.
    push_subscribed_device = request.cookies.get('wc_push') == '1'

    return render_template('dashboard.html',
                           active_favs=active_favs,
                           other_favs=other_favs,
                           fav_count=fav_count,
                           active_count=active_count,
                           max_favs=max_favs,
                           max_active=max_active,
                           at_max_favs=not current_user.is_admin and fav_count >= max_favs,
                           at_max_active=active_count >= max_active,
                           spot_summaries=spot_summaries,
                           push_subscribed_device=push_subscribed_device)
