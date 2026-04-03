from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from models import db, User, Spot, UserFavouriteSpot, AdminSettings
from extensions import bcrypt

admin_bp = Blueprint('admin_bp', __name__)


def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/admin/users')
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.email).all()
    settings = AdminSettings.query.first()
    return render_template('admin/users.html', users=all_users, settings=settings)


@admin_bp.route('/admin/users/<int:user_id>')
@login_required
def user_detail(user_id):
    if not current_user.is_admin and current_user.id != user_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('main.index'))
    user = User.query.get_or_404(user_id)
    created_spots = Spot.query.filter_by(created_by=user_id).order_by(Spot.name).all()
    favs = (UserFavouriteSpot.query
            .filter_by(user_id=user_id)
            .join(Spot)
            .order_by(Spot.name)
            .all())
    alert_favs = [f for f in favs if f.is_active]
    other_favs  = [f for f in favs if not f.is_active]
    return render_template('admin/user_detail.html',
                           user=user,
                           created_spots=created_spots,
                           alert_favs=alert_favs,
                           other_favs=other_favs)


@admin_bp.route('/admin/users/<int:user_id>/edit', methods=['POST'])
@login_required
def edit_user(user_id):
    if not current_user.is_admin and current_user.id != user_id:
        flash('Access denied.', 'danger')
        return redirect(url_for('main.index'))
    user = User.query.get_or_404(user_id)
    user.first_name  = request.form.get('first_name', '').strip() or user.first_name
    user.last_name   = request.form.get('last_name', '').strip()  or user.last_name
    user.weight_kg   = float(request.form.get('weight_kg', user.weight_kg))
    user.min_wind    = float(request.form.get('min_wind',  user.min_wind))
    user.max_wind    = float(request.form.get('max_wind',  user.max_wind))
    user.whatsapp_dial_code = request.form.get('whatsapp_dial_code', '+44').strip()
    user.whatsapp_number    = request.form.get('whatsapp_number', '').strip() or None
    user.whatsapp_enabled   = 'whatsapp_enabled'  in request.form
    user.whatsapp_today     = 'whatsapp_today'     in request.form
    user.whatsapp_tomorrow  = 'whatsapp_tomorrow'  in request.form
    user.whatsapp_day_after = 'whatsapp_day_after' in request.form
    user.timezone           = request.form.get('timezone', 'Europe/London')
    slots = request.form.getlist('available_slots')
    if slots:
        user.available_slots = ','.join(slots)
    db.session.commit()
    flash('Profile updated.', 'success')
    return redirect(url_for('admin_bp.user_detail', user_id=user_id))


@admin_bp.route('/admin/users/<int:user_id>/send-whatsapp', methods=['POST'])
@login_required
@admin_required
def send_whatsapp(user_id):
    user = User.query.get_or_404(user_id)
    message = request.form.get('message', '').strip()
    if not message:
        flash('Message cannot be empty.', 'danger')
        return redirect(url_for('admin_bp.users'))
    if not user.whatsapp_number:
        flash(f'{user.name} has no phone number saved.', 'danger')
        return redirect(url_for('admin_bp.users'))
    from whatsapp import send_whatsapp as _send
    ok, result = _send(user.whatsapp_dial_code or '+44', user.whatsapp_number, message)
    if ok:
        flash(f'WhatsApp sent to {user.name} ✓', 'success')
    else:
        flash(f'Failed to send to {user.name}: {result}', 'danger')
    return redirect(url_for('admin_bp.users'))


@admin_bp.route('/admin/send-all-alerts', methods=['POST'])
@login_required
@admin_required
def send_all_alerts():
    from alerts import send_all_alerts as _send_all
    app_url = request.host_url.rstrip('/')
    results = _send_all(app_url)
    sent    = sum(1 for _, ok, _ in results if ok)
    skipped = sum(1 for _, ok, detail in results if not ok and 'No qualifying' in detail)
    failed  = len(results) - sent - skipped
    parts   = []
    if sent:    parts.append(f'{sent} sent')
    if skipped: parts.append(f'{skipped} had nothing to report')
    if failed:  parts.append(f'{failed} failed')
    flash('Alerts: ' + ', '.join(parts) if parts else 'No users with WhatsApp enabled.', 'info')
    return redirect(url_for('admin_bp.users'))


@admin_bp.route('/admin/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@admin_required
def toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot disable your own account.', 'danger')
        return redirect(url_for('admin_bp.user_detail', user_id=user_id))
    user.is_active = not user.is_active
    db.session.commit()
    status = 'enabled' if user.is_active else 'disabled'
    flash(f'Account for {user.email} has been {status}.', 'success')
    return redirect(url_for('admin_bp.user_detail', user_id=user_id))


@admin_bp.route('/admin/users/<int:user_id>/set-password', methods=['POST'])
@login_required
@admin_required
def set_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()
    confirm = request.form.get('confirm_password', '').strip()
    if not new_password or len(new_password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin_bp.user_detail', user_id=user_id))
    if new_password != confirm:
        flash('Passwords do not match.', 'danger')
        return redirect(url_for('admin_bp.user_detail', user_id=user_id))
    user.password = bcrypt.generate_password_hash(new_password).decode('utf-8')
    db.session.commit()
    flash(f'Password updated for {user.email}.', 'success')
    return redirect(url_for('admin_bp.user_detail', user_id=user_id))


@admin_bp.route('/admin/settings', methods=['POST'])
@login_required
@admin_required
def update_settings():
    settings = AdminSettings.query.first()
    new_max_favs   = int(request.form.get('max_favourite_spots', 3))
    new_max_active = int(request.form.get('max_active_spots', 2))

    # Can't reduce below the maximum any user currently has
    max_favs_in_use = db.session.query(
        db.func.count(UserFavouriteSpot.id)
    ).filter_by().group_by(UserFavouriteSpot.user_id).order_by(
        db.func.count(UserFavouriteSpot.id).desc()
    ).first()
    max_active_in_use = db.session.query(
        db.func.count(UserFavouriteSpot.id)
    ).filter_by(is_active=True).group_by(UserFavouriteSpot.user_id).order_by(
        db.func.count(UserFavouriteSpot.id).desc()
    ).first()

    max_favs_in_use   = max_favs_in_use[0]   if max_favs_in_use   else 0
    max_active_in_use = max_active_in_use[0]  if max_active_in_use else 0

    if new_max_favs < max_favs_in_use:
        flash(f'Cannot reduce max favourites below {max_favs_in_use} — a user already has that many.', 'danger')
        return redirect(url_for('admin_bp.users'))

    if new_max_active < max_active_in_use:
        flash(f'Cannot reduce max alert-me spots below {max_active_in_use} — a user already has that many.', 'danger')
        return redirect(url_for('admin_bp.users'))

    if new_max_active > new_max_favs:
        flash('Max alert-me spots cannot exceed max favourite spots.', 'danger')
        return redirect(url_for('admin_bp.users'))

    settings.max_favourite_spots     = new_max_favs
    settings.max_active_spots        = new_max_active
    settings.default_min_tide_percent = float(request.form.get('default_min_tide_percent', 0.0))
    settings.default_max_tide_percent = float(request.form.get('default_max_tide_percent', 90.0))
    db.session.commit()
    flash('Settings updated.', 'success')
    return redirect(url_for('admin_bp.users'))
