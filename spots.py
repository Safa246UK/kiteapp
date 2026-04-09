from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime
import os
from models import db, Spot, UserFavouriteSpot, SpotNote, User, AdminSettings, WeatherCache, TideCache, COMPASS_POINTS
from weather import get_forecast_table, RATING_COLOURS

spots = Blueprint('spots', __name__)


@spots.route('/spots')
@login_required
def index():
    if current_user.is_admin:
        all_spots = Spot.query.order_by(Spot.name).all()
    else:
        all_spots = Spot.query.filter_by(is_retired=False).order_by(Spot.name).all()
    user_favourites = {f.spot_id for f in UserFavouriteSpot.query.filter_by(user_id=current_user.id).all()}
    user_actives = {f.spot_id for f in UserFavouriteSpot.query.filter_by(user_id=current_user.id, is_active=True).all()}
    settings  = AdminSettings.query.first()
    max_favs  = settings.max_favourite_spots if settings else 3
    fav_count = len(user_favourites)
    return render_template('spots/index.html',
                           spots=all_spots,
                           user_favourites=user_favourites,
                           user_actives=user_actives,
                           compass_points=COMPASS_POINTS,
                           settings=settings,
                           at_max_favs=not current_user.is_admin and fav_count >= max_favs,
                           max_favs=max_favs)


@spots.route('/spots/add', methods=['POST'])
@login_required
def add():
    settings = AdminSettings.query.first()
    max_favs = settings.max_favourite_spots if settings else 3
    fav_count = UserFavouriteSpot.query.filter_by(user_id=current_user.id).count()

    if not current_user.is_admin and fav_count >= max_favs:
        flash(f'You have reached your maximum of {max_favs} favourite spots. Unlink a favourite before creating a new one.', 'danger')
        return redirect(url_for('spots.index'))

    name = request.form.get('name', '').strip()
    lat = request.form.get('latitude')
    lng = request.form.get('longitude')
    description = request.form.get('description', '').strip()
    min_tide = request.form.get('min_tide_percent', 20)
    max_tide = request.form.get('max_tide_percent', 85)
    perfect = request.form.get('perfect_directions', '')
    good = request.form.get('good_directions', '')
    okay = request.form.get('okay_directions', '')
    poor = request.form.get('poor_directions', '')
    dangerous = request.form.get('dangerous_directions', '')

    if not name or not lat or not lng:
        flash('Name and location are required.', 'danger')
        return redirect(url_for('spots.index'))

    # Auto-detect timezone from coordinates
    try:
        from timezonefinder import TimezoneFinder
        spot_tz = TimezoneFinder().timezone_at(lat=float(lat), lng=float(lng)) or 'Europe/London'
    except Exception:
        spot_tz = 'Europe/London'

    is_seasonal   = 'is_seasonal'   in request.form
    is_landlocked = 'is_landlocked' in request.form
    spot = Spot(
        name=name,
        latitude=float(lat),
        longitude=float(lng),
        description=description,
        min_tide_percent=float(min_tide),
        max_tide_percent=float(max_tide),
        perfect_directions=perfect,
        good_directions=good,
        okay_directions=okay,
        poor_directions=poor,
        dangerous_directions=dangerous,
        created_by=current_user.id,
        is_landlocked=is_landlocked,
        timezone=spot_tz,
        season_start_month=int(request.form.get('season_start_month', 1)) if is_seasonal else None,
        season_start_day=int(request.form.get('season_start_day', 1))     if is_seasonal else None,
        season_end_month=int(request.form.get('season_end_month', 12))    if is_seasonal else None,
        season_end_day=int(request.form.get('season_end_day', 31))        if is_seasonal else None,
    )
    db.session.add(spot)
    db.session.flush()  # Get spot.id before commit

    # Auto-favourite the newly created spot (only for non-admins under the limit)
    if not current_user.is_admin and fav_count < max_favs:
        db.session.add(UserFavouriteSpot(user_id=current_user.id, spot_id=spot.id))
    db.session.commit()

    # Fetch weather immediately so data is available straight away
    try:
        from weather import fetch_and_cache_weather, compute_and_cache_summary
        fetch_and_cache_weather(spot)
        compute_and_cache_summary(spot)
    except Exception as e:
        print(f"[Weather] Initial fetch failed for {spot.name}: {e}")

    flash(f'Spot "{name}" created successfully!', 'success')
    return redirect(url_for('main.index'))


@spots.route('/spots/<int:spot_id>')
@login_required
def detail(spot_id):
    spot = Spot.query.get_or_404(spot_id)
    notes = SpotNote.query.filter_by(spot_id=spot_id).order_by(SpotNote.created_at.desc()).all()
    watchers = db.session.query(User).join(UserFavouriteSpot).filter(
        UserFavouriteSpot.spot_id == spot_id
    ).all()
    is_favourite = UserFavouriteSpot.query.filter_by(user_id=current_user.id, spot_id=spot_id).first()

    from datetime import datetime, timedelta

    # Refresh weather if missing, older than 3 hours, or cache has no usable hourly data
    import json as _json
    w_cache = WeatherCache.query.filter_by(spot_id=spot_id).first()
    _cache_bad = False
    if w_cache and w_cache.forecast_json:
        try:
            _d = _json.loads(w_cache.forecast_json)
            _cache_bad = not _d.get('weather', {}).get('hourly', {}).get('time')
        except Exception:
            _cache_bad = True
    weather_stale = (
        not w_cache or
        w_cache.fetched_at is None or
        _cache_bad or
        w_cache.fetched_at < datetime.utcnow() - timedelta(hours=3)
    )
    if weather_stale:
        try:
            from weather import fetch_and_cache_weather
            fetch_and_cache_weather(spot)
        except Exception as e:
            print(f"[Weather] On-demand fetch failed: {e}")

    # Refresh tides if missing or older than 12 hours (API has daily limits)
    t_cache = TideCache.query.filter_by(spot_id=spot_id).first()
    tides_stale = (
        not t_cache or
        t_cache.fetched_at is None or
        t_cache.fetched_at < datetime.utcnow() - timedelta(hours=12)
    )
    if tides_stale:
        try:
            from tides import fetch_and_cache_tides
            api_key = os.environ.get('ADMIRALTY_API_KEY', '')
            if api_key:
                fetch_and_cache_tides(spot, api_key)
        except Exception as e:
            print(f"[Tides] On-demand fetch failed: {e}")

    forecast_slots, fetched_at, has_tide, tide_real = get_forecast_table(spot, user=current_user)
    tc = TideCache.query.filter_by(spot_id=spot_id).first()
    no_tide_station = not spot.is_landlocked and tc is not None and not tc.station_id
    from log_utils import log_event
    log_event(current_user.email, 'spot_viewed', detail=spot.name,
              spot_id=spot.id, user_id=current_user.id)
    return render_template('spots/detail.html', spot=spot, notes=notes,
                           watchers=watchers, is_favourite=is_favourite,
                           compass_points=COMPASS_POINTS,
                           forecast_slots=forecast_slots,
                           fetched_at=fetched_at,
                           has_tide=has_tide,
                           tide_real=tide_real,
                           no_tide_station=no_tide_station,
                           rating_colours=RATING_COLOURS)


@spots.route('/spots/<int:spot_id>/favourite', methods=['POST'])
@login_required
def toggle_favourite(spot_id):
    settings = AdminSettings.query.first()
    existing = UserFavouriteSpot.query.filter_by(user_id=current_user.id, spot_id=spot_id).first()
    next_page = request.form.get('next', 'dashboard')
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash('Spot removed from your favourites.', 'info')
    else:
        count = UserFavouriteSpot.query.filter_by(user_id=current_user.id).count()
        max_favs = settings.max_favourite_spots if settings else 3
        if count >= max_favs:
            flash(f'You have reached your maximum of {max_favs} favourite spots. Unlink a favourite first.', 'danger')
        else:
            db.session.add(UserFavouriteSpot(user_id=current_user.id, spot_id=spot_id))
            db.session.commit()
            flash('Spot added to your favourites!', 'success')
    if next_page == 'detail':
        return redirect(url_for('spots.detail', spot_id=spot_id))
    return redirect(url_for('main.index'))


@spots.route('/spots/<int:spot_id>/activate', methods=['POST'])
@login_required
def toggle_active(spot_id):
    settings = AdminSettings.query.first()
    fav = UserFavouriteSpot.query.filter_by(user_id=current_user.id, spot_id=spot_id).first()
    if not fav:
        flash('Add this spot to your favourites first.', 'danger')
        return redirect(url_for('main.index'))
    if fav.is_active:
        fav.is_active = False
        db.session.commit()
    else:
        active_count = UserFavouriteSpot.query.filter_by(user_id=current_user.id, is_active=True).count()
        max_active = settings.max_active_spots if settings else 2
        if active_count >= max_active:
            flash(f'You can only have {max_active} alert-me spots. Turn off another one first.', 'danger')
            return redirect(url_for('main.index'))
        fav.is_active = True
        db.session.commit()
    return redirect(url_for('main.index'))


@spots.route('/spots/<int:spot_id>/note', methods=['POST'])
@login_required
def add_note(spot_id):
    note_text = request.form.get('note', '').strip()
    if note_text:
        db.session.add(SpotNote(spot_id=spot_id, user_id=current_user.id, note=note_text))
        db.session.commit()
        flash('Note added.', 'success')
    return redirect(url_for('spots.detail', spot_id=spot_id))


@spots.route('/spots/note/<int:note_id>/delete', methods=['POST'])
@login_required
def delete_note(note_id):
    note = SpotNote.query.get_or_404(note_id)
    if note.user_id == current_user.id or current_user.is_admin:
        db.session.delete(note)
        db.session.commit()
        flash('Note deleted.', 'info')
    else:
        flash('You do not have permission to delete this note.', 'danger')
    return redirect(url_for('spots.detail', spot_id=note.spot_id))


@spots.route('/spots/<int:spot_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(spot_id):
    if not current_user.is_admin:
        flash('Only admins can edit spots.', 'danger')
        return redirect(url_for('spots.detail', spot_id=spot_id))
    spot = Spot.query.get_or_404(spot_id)
    if request.method == 'POST':
        spot.name        = request.form.get('name', '').strip()
        spot.description = request.form.get('description', '').strip()
        spot.latitude    = float(request.form.get('latitude'))
        spot.longitude   = float(request.form.get('longitude'))
        try:
            from timezonefinder import TimezoneFinder
            spot.timezone = TimezoneFinder().timezone_at(lat=spot.latitude, lng=spot.longitude) or 'Europe/London'
        except Exception:
            spot.timezone = spot.timezone or 'Europe/London'
        spot.min_tide_percent = float(request.form.get('min_tide_percent', 20))
        spot.max_tide_percent = float(request.form.get('max_tide_percent', 85))
        spot.perfect_directions   = request.form.get('perfect_directions', '')
        spot.good_directions      = request.form.get('good_directions', '')
        spot.okay_directions      = ''   # retired — legacy data cleared on every save
        spot.poor_directions      = request.form.get('poor_directions', '')
        spot.dangerous_directions = request.form.get('dangerous_directions', '')
        spot.is_landlocked = 'is_landlocked' in request.form
        if 'is_seasonal' in request.form:
            spot.season_start_month = int(request.form.get('season_start_month', 1))
            spot.season_start_day   = int(request.form.get('season_start_day', 1))
            spot.season_end_month   = int(request.form.get('season_end_month', 12))
            spot.season_end_day     = int(request.form.get('season_end_day', 31))
        else:
            spot.season_start_month = None
            spot.season_start_day   = None
            spot.season_end_month   = None
            spot.season_end_day     = None
        db.session.commit()
        flash(f'Spot "{spot.name}" updated.', 'success')
        return redirect(url_for('spots.detail', spot_id=spot_id))
    creator = User.query.get(spot.created_by)
    return render_template('spots/edit.html', spot=spot, creator=creator)


@spots.route('/spots/<int:spot_id>/retire', methods=['POST'])
@login_required
def retire(spot_id):
    if not current_user.is_admin:
        flash('Only admins can retire spots.', 'danger')
        return redirect(url_for('spots.detail', spot_id=spot_id))
    spot = Spot.query.get_or_404(spot_id)
    spot.is_retired = not spot.is_retired
    spot.retired_at = datetime.utcnow() if spot.is_retired else None
    db.session.commit()
    status = 'disabled' if spot.is_retired else 'enabled'
    flash(f'Spot "{spot.name}" has been {status}.', 'success')
    return redirect(url_for('spots.manage'))



@spots.route('/spots/manage')
@login_required
def manage():
    if not current_user.is_admin:
        flash('Admin access only.', 'danger')
        return redirect(url_for('main.index'))
    all_spots = Spot.query.order_by(Spot.name).all()
    watcher_counts = {s.id: len(s.favourited_by) for s in all_spots}
    return render_template('spots/manage.html', spots=all_spots, watcher_counts=watcher_counts)


@spots.route('/spots/api/all')
@login_required
def api_all():
    if current_user.is_admin:
        all_spots = Spot.query.all()
    else:
        all_spots = Spot.query.filter_by(is_retired=False).all()
    user_favourites = {f.spot_id for f in UserFavouriteSpot.query.filter_by(user_id=current_user.id).all()}
    return jsonify([{
        'id': s.id,
        'name': s.name,
        'lat': s.latitude,
        'lng': s.longitude,
        'description': s.description,
        'is_favourite': s.id in user_favourites,
        'watcher_count': len(s.favourited_by),
        'is_retired': s.is_retired
    } for s in all_spots])
