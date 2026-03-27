from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from models import db, Spot, UserFavouriteSpot, SpotNote, User, AdminSettings, COMPASS_POINTS

spots = Blueprint('spots', __name__)


@spots.route('/spots')
@login_required
def index():
    if current_user.is_admin:
        all_spots = Spot.query.all()
    else:
        all_spots = Spot.query.filter_by(is_retired=False).all()
    user_favourites = {f.spot_id for f in UserFavouriteSpot.query.filter_by(user_id=current_user.id).all()}
    user_actives = {f.spot_id for f in UserFavouriteSpot.query.filter_by(user_id=current_user.id, is_active=True).all()}
    settings = AdminSettings.query.first()
    return render_template('spots/index.html',
                           spots=all_spots,
                           user_favourites=user_favourites,
                           user_actives=user_actives,
                           compass_points=COMPASS_POINTS,
                           settings=settings)


@spots.route('/spots/add', methods=['POST'])
@login_required
def add():
    name = request.form.get('name', '').strip()
    lat = request.form.get('latitude')
    lng = request.form.get('longitude')
    description = request.form.get('description', '').strip()
    min_tide = request.form.get('min_tide_percent', 20)
    max_tide = request.form.get('max_tide_percent', 85)
    min_wind = request.form.get('min_wind', 12)
    max_wind = request.form.get('max_wind', 35)
    perfect = request.form.get('perfect_directions', '')
    good = request.form.get('good_directions', '')
    okay = request.form.get('okay_directions', '')
    poor = request.form.get('poor_directions', '')
    dangerous = request.form.get('dangerous_directions', '')

    if not name or not lat or not lng:
        flash('Name and location are required.', 'danger')
        return redirect(url_for('spots.index'))

    spot = Spot(
        name=name,
        latitude=float(lat),
        longitude=float(lng),
        description=description,
        min_tide_percent=float(min_tide),
        max_tide_percent=float(max_tide),
        min_wind=float(min_wind),
        max_wind=float(max_wind),
        perfect_directions=perfect,
        good_directions=good,
        okay_directions=okay,
        poor_directions=poor,
        dangerous_directions=dangerous,
        created_by=current_user.id
    )
    db.session.add(spot)
    db.session.commit()
    flash(f'Spot "{name}" added successfully!', 'success')
    return redirect(url_for('spots.index'))


@spots.route('/spots/<int:spot_id>')
@login_required
def detail(spot_id):
    spot = Spot.query.get_or_404(spot_id)
    notes = SpotNote.query.filter_by(spot_id=spot_id).order_by(SpotNote.created_at.desc()).all()
    watchers = db.session.query(User).join(UserFavouriteSpot).filter(
        UserFavouriteSpot.spot_id == spot_id
    ).all()
    is_favourite = UserFavouriteSpot.query.filter_by(user_id=current_user.id, spot_id=spot_id).first()
    return render_template('spots/detail.html', spot=spot, notes=notes,
                           watchers=watchers, is_favourite=is_favourite,
                           compass_points=COMPASS_POINTS)


@spots.route('/spots/<int:spot_id>/favourite', methods=['POST'])
@login_required
def toggle_favourite(spot_id):
    settings = AdminSettings.query.first()
    existing = UserFavouriteSpot.query.filter_by(user_id=current_user.id, spot_id=spot_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash('Spot removed from your favourites.', 'info')
    else:
        count = UserFavouriteSpot.query.filter_by(user_id=current_user.id).count()
        max_favs = settings.max_favourite_spots if settings else 10
        if count >= max_favs:
            flash(f'You can only have {max_favs} favourite spots.', 'danger')
        else:
            db.session.add(UserFavouriteSpot(user_id=current_user.id, spot_id=spot_id))
            db.session.commit()
            flash('Spot added to your favourites!', 'success')
    return redirect(url_for('spots.detail', spot_id=spot_id))


@spots.route('/spots/<int:spot_id>/activate', methods=['POST'])
@login_required
def toggle_active(spot_id):
    settings = AdminSettings.query.first()
    fav = UserFavouriteSpot.query.filter_by(user_id=current_user.id, spot_id=spot_id).first()
    if not fav:
        flash('Add this spot to your favourites first.', 'danger')
        return redirect(url_for('spots.detail', spot_id=spot_id))
    if fav.is_active:
        fav.is_active = False
        db.session.commit()
        flash('WhatsApp alerts disabled for this spot.', 'info')
    else:
        active_count = UserFavouriteSpot.query.filter_by(user_id=current_user.id, is_active=True).count()
        max_active = settings.max_active_spots if settings else 3
        if active_count >= max_active:
            flash(f'You can only have {max_active} active spots for alerts.', 'danger')
        else:
            fav.is_active = True
            db.session.commit()
            flash('WhatsApp alerts enabled for this spot!', 'success')
    return redirect(url_for('spots.detail', spot_id=spot_id))


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
        spot.min_tide_percent = float(request.form.get('min_tide_percent', 20))
        spot.max_tide_percent = float(request.form.get('max_tide_percent', 85))
        spot.min_wind    = float(request.form.get('min_wind', 12))
        spot.max_wind    = float(request.form.get('max_wind', 35))
        spot.perfect_directions   = request.form.get('perfect_directions', '')
        spot.good_directions      = request.form.get('good_directions', '')
        spot.okay_directions      = request.form.get('okay_directions', '')
        spot.poor_directions      = request.form.get('poor_directions', '')
        spot.dangerous_directions = request.form.get('dangerous_directions', '')
        db.session.commit()
        flash(f'Spot "{spot.name}" updated.', 'success')
        return redirect(url_for('spots.detail', spot_id=spot_id))
    return render_template('spots/edit.html', spot=spot)


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
    status = 'retired' if spot.is_retired else 'reinstated'
    flash(f'Spot "{spot.name}" has been {status}.', 'success')
    return redirect(url_for('spots.index'))


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
