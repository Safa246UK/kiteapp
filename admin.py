import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from models import db, User, Spot, UserFavouriteSpot, AdminSettings, PushSubscription, AppLog
from extensions import bcrypt

admin_bp = Blueprint('admin_bp', __name__)

# This account is permanently admin and cannot be demoted under any circumstances
PROTECTED_ADMIN_EMAIL = 'ken@hamptons.me.uk'


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
    push_subs   = PushSubscription.query.filter_by(user_id=user_id).order_by(PushSubscription.created_at.desc()).all()
    if current_user.is_admin and current_user.id != user_id:
        from log_utils import log_event
        log_event(current_user.email, 'user_profile_viewed',
                  detail=f'Viewed profile of {user.email}', user_id=user_id)
    return render_template('admin/user_detail.html',
                           user=user,
                           created_spots=created_spots,
                           alert_favs=alert_favs,
                           other_favs=other_favs,
                           push_subs=push_subs)


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
    user.notification_type  = request.form.get('notification_type', 'push')
    slots = request.form.getlist('available_slots')
    if slots:
        user.available_slots = ','.join(slots)
    db.session.commit()
    from log_utils import log_event
    log_event(current_user.email, 'user_profile_updated',
              detail=f'Updated profile of {user.email}', user_id=user_id)
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
    from log_utils import log_event
    if ok:
        log_event(current_user.email, 'whatsapp_sent_admin',
                  detail=f'Sent WhatsApp to {user.email}', user_id=user.id)
        flash(f'WhatsApp sent to {user.name} ✓', 'success')
    else:
        log_event(current_user.email, 'whatsapp_failed_admin',
                  detail=f'Failed to send WhatsApp to {user.email}: {result}', user_id=user.id)
        flash(f'Failed to send to {user.name}: {result}', 'danger')
    return redirect(url_for('admin_bp.users'))


@admin_bp.route('/admin/refresh-weather', methods=['POST'])
def refresh_weather():
    """Trigger a weather + tide refresh for all spots.

    Accepts either:
    - A logged-in admin session (manual button press), or
    - A CRON_SECRET token in the X-Cron-Secret header (Render cron job).
    """
    cron_secret = os.environ.get('CRON_SECRET', '')
    incoming    = request.headers.get('X-Cron-Secret', '')
    from_cron   = cron_secret and incoming == cron_secret

    if not from_cron:
        # Fall back to normal admin session check
        if not current_user.is_authenticated or not current_user.is_admin:
            from flask import abort
            abort(403)

    from scheduler import refresh_all_weather, refresh_all_tides, refresh_all_summaries
    from log_utils import log_event
    from datetime import datetime, timezone

    if from_cron:
        now_utc = datetime.now(timezone.utc)
        log_event('CRON', 'cron_started',
                  detail=f"Hourly cron started at {now_utc.strftime('%Y-%m-%d %H:%M')} UTC")

    w_ok = w_failed = 0
    t_ok = t_skip = t_fail = 0
    alert_sent = alert_skip = alert_fail = 0
    errors = []

    try:
        try:
            w_ok, w_failed = refresh_all_weather()
        except Exception as e:
            errors.append(f"Weather phase failed: {e}")
            print(f"[Cron] Weather phase failed: {e}")

        try:
            t_ok, t_skip, t_fail = refresh_all_tides()
        except Exception as e:
            errors.append(f"Tides phase failed: {e}")
            print(f"[Cron] Tides phase failed: {e}")

        try:
            refresh_all_summaries()
        except Exception as e:
            errors.append(f"Summaries phase failed: {e}")
            print(f"[Cron] Summaries phase failed: {e}")

        if from_cron:
            try:
                from alerts import send_due_alerts
                app_url = request.host_url.rstrip('/')
                results = send_due_alerts(app_url)
                alert_sent = sum(1 for _, ok, _ in results if ok)
                alert_skip = sum(1 for _, ok, d in results if not ok and 'No qualifying' in d)
                alert_fail = sum(1 for _, ok, d in results if not ok and 'No qualifying' not in d)
            except Exception as ae:
                errors.append(f"Alerts phase failed: {ae}")
                print(f"[Cron] Alerts phase failed: {ae}")

        if from_cron:
            try:
                settings = AdminSettings.query.first()
                if settings and settings.billing_enabled:
                    from billing_emails import run_billing_cron
                    from datetime import date as _date
                    billing_results = run_billing_cron(_date.today(), app_url)
                    if billing_results:
                        log_event('CRON', 'billing_cron_ran',
                                  detail=(f"Warnings sent: {billing_results['warnings_sent']}, "
                                          f"failed: {billing_results['warnings_failed']}, "
                                          f"suspended: {billing_results['suspended']}"))
            except Exception as be:
                errors.append(f"Billing phase failed: {be}")
                print(f"[Cron] Billing phase failed: {be}")

        if not from_cron:
            actor = current_user.email if current_user.is_authenticated else 'ADMIN'
            log_event(actor, 'weather_refresh_manual',
                      detail=f'Weather: {w_ok} updated, {w_failed} failed | Tides: {t_ok} updated, {t_skip} skipped, {t_fail} failed')
            flash('✅ Weather and tide data refreshed for all spots.', 'success')
    finally:
        if from_cron:
            detail = (f"Weather: {w_ok} updated, {w_failed} failed | "
                      f"Tides: {t_ok} updated, {t_skip} skipped, {t_fail} failed | "
                      f"Alerts: {alert_sent} sent, {alert_skip} skipped, {alert_fail} failed")
            if errors:
                detail += " | ERRORS: " + "; ".join(errors)
            log_event('CRON', 'cron_completed', detail=detail)

    if from_cron:
        return 'OK', 200
    return redirect(url_for('spots.manage'))


@admin_bp.route('/admin/send-all-alerts', methods=['POST'])
@login_required
@admin_required
def send_all_alerts():
    from alerts import send_all_alerts as _send_all
    app_url = request.host_url.rstrip('/')
    results = _send_all(app_url)
    _skip_phrases = ('No qualifying', 'No push subscriptions', 'disabled', 'Notifications disabled')
    sent_list    = [(u, d) for u, ok, d in results if ok]
    skipped_list = [(u, d) for u, ok, d in results if not ok and any(p in d for p in _skip_phrases)]
    failed_list  = [(u, d) for u, ok, d in results if not ok and not any(p in d for p in _skip_phrases)]
    parts = []
    if sent_list:    parts.append(f'{len(sent_list)} sent')
    if skipped_list: parts.append(f'{len(skipped_list)} had nothing to send')
    if failed_list:
        parts.append(f'{len(failed_list)} failed')
        for u, d in failed_list:
            flash(f'❌ {u.email}: {d}', 'danger')
    from log_utils import log_event
    log_event(current_user.email, 'alerts_sent_all',
              detail=f'{len(sent_list)} sent, {len(skipped_list)} skipped, {len(failed_list)} failed')
    flash('Alerts: ' + ', '.join(parts) if parts else 'No users with alerts enabled.', 'info')
    return redirect(url_for('admin_bp.users'))


@admin_bp.route('/admin/users/<int:user_id>/toggle-role', methods=['POST'])
@login_required
@admin_required
def toggle_role(user_id):
    user = User.query.get_or_404(user_id)

    if user.email.lower() == PROTECTED_ADMIN_EMAIL:
        flash(f'{user.email} is a protected account — its admin status cannot be changed.', 'danger')
        return redirect(url_for('admin_bp.users'))

    if user.id == current_user.id:
        flash('You cannot change your own role.', 'danger')
        return redirect(url_for('admin_bp.users'))

    password = request.form.get('admin_password', '')
    if not bcrypt.check_password_hash(current_user.password, password):
        flash('Incorrect password — role not changed.', 'danger')
        return redirect(url_for('admin_bp.users'))

    user.is_admin = not user.is_admin
    db.session.commit()
    new_role = 'Admin' if user.is_admin else 'User'
    from log_utils import log_event
    log_event(current_user.email, 'user_role_changed',
              detail=f'{user.email} is now {new_role}', user_id=user.id)
    flash(f'{user.name} is now a {new_role}.', 'success')
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
    from log_utils import log_event
    log_event(current_user.email, 'user_account_toggled',
              detail=f'{user.email} account {status}', user_id=user_id)
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
    from log_utils import log_event
    log_event(current_user.email, 'user_password_reset_admin',
              detail=f'Admin reset password for {user.email}', user_id=user_id)
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

    # Redirect back to whichever admin page submitted the form
    source = request.form.get('source', 'users')
    redirect_target = url_for('spots.manage') if source == 'spots' else url_for('admin_bp.users')

    if new_max_favs < max_favs_in_use:
        flash(f'Cannot reduce max favourites below {max_favs_in_use} — a user already has that many.', 'danger')
        return redirect(redirect_target)

    if new_max_active < max_active_in_use:
        flash(f'Cannot reduce max alert-me spots below {max_active_in_use} — a user already has that many.', 'danger')
        return redirect(redirect_target)

    if new_max_active > new_max_favs:
        flash('Max alert-me spots cannot exceed max favourite spots.', 'danger')
        return redirect(redirect_target)

    billing_enabled = 'billing_enabled' in request.form
    settings.max_favourite_spots      = new_max_favs
    settings.max_active_spots         = new_max_active
    settings.default_min_tide_percent = float(request.form.get('default_min_tide_percent', 0.0))
    settings.default_max_tide_percent = float(request.form.get('default_max_tide_percent', 90.0))
    settings.billing_enabled          = billing_enabled
    db.session.commit()
    from log_utils import log_event
    log_event(current_user.email, 'settings_updated',
              detail=f'max_favs={new_max_favs}, max_active={new_max_active}, billing_enabled={billing_enabled}')
    flash('Settings updated.', 'success')
    return redirect(redirect_target)


@admin_bp.route('/admin/logs')
@login_required
@admin_required
def logs():
    import os
    from models import AppLog
    from datetime import datetime, timedelta

    # Filters
    hours   = int(request.args.get('hours', 24))
    actor   = request.args.get('actor', '').strip()
    etype   = request.args.get('event_type', '').strip()
    cutoff  = datetime.utcnow() - timedelta(hours=hours)

    query = AppLog.query.filter(AppLog.timestamp >= cutoff)
    if actor:
        query = query.filter(AppLog.actor.ilike(f'%{actor}%'))
    if etype:
        query = query.filter(AppLog.event_type == etype)

    entries      = query.order_by(AppLog.timestamp.desc()).limit(1000).all()
    event_types  = [r[0] for r in db.session.query(AppLog.event_type).distinct().order_by(AppLog.event_type).all()]
    retention    = int(os.environ.get('LOG_RETENTION_DAYS', 999))

    return render_template('admin/logs.html',
                           entries=entries, hours=hours,
                           actor=actor, etype=etype,
                           event_types=event_types,
                           retention=retention)


@admin_bp.route('/admin/logs/download')
@login_required
@admin_required
def logs_download():
    """Download all logs as a CSV file."""
    import csv
    import io
    from datetime import datetime
    from flask import Response
    from models import AppLog

    rows = AppLog.query.order_by(AppLog.timestamp.desc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['Timestamp (UTC)', 'Actor', 'Event Type', 'Detail', 'Spot ID', 'User ID'])
    for r in rows:
        writer.writerow([
            r.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            r.actor,
            r.event_type,
            r.detail or '',
            r.spot_id or '',
            r.user_id or '',
        ])

    filename = f"windchaser_logs_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        buf.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


# ---------------------------------------------------------------------------
# Billing admin actions
# ---------------------------------------------------------------------------

@admin_bp.route('/admin/users/<int:user_id>/toggle-free-for-life', methods=['POST'])
@login_required
@admin_required
def toggle_free_for_life(user_id):
    user = User.query.get_or_404(user_id)
    user.is_free_for_life = not user.is_free_for_life
    db.session.commit()
    from log_utils import log_event
    state = 'granted' if user.is_free_for_life else 'revoked'
    log_event(current_user.email, 'billing_free_for_life',
              detail=f'{user.email} — free-for-life {state}', user_id=user.id)
    flash(f'Free-for-life {state} for {user.name}.', 'success')
    return redirect(url_for('admin_bp.user_detail', user_id=user_id))


@admin_bp.route('/admin/users/<int:user_id>/send-payment-email', methods=['POST'])
@login_required
@admin_required
def send_payment_email(user_id):
    user = User.query.get_or_404(user_id)
    from billing_emails import send_trial_ending_warning, send_payment_failed_email
    from models import db

    # Auto-fill missing billing dates for users created before billing was deployed
    if not user.first_billing_date and not user.is_free_for_life:
        from datetime import date
        from billing import calculate_first_billing_date
        user.first_billing_date = calculate_first_billing_date(date.today())
        db.session.commit()

    app_url = request.host_url.rstrip('/')
    if user.subscription_status in ('trial',):
        ok, detail = send_trial_ending_warning(user, app_url)
    else:
        ok, detail = send_payment_failed_email(user, app_url)
    from log_utils import log_event
    if ok:
        log_event(current_user.email, 'billing_payment_email_sent',
                  detail=f'Sent payment email to {user.email}', user_id=user.id)
        flash(f'Payment email sent to {user.email}.', 'success')
    else:
        flash(f'Failed to send email: {detail}', 'danger')
    return redirect(url_for('admin_bp.user_detail', user_id=user_id))


@admin_bp.route('/admin/users/<int:user_id>/reinstate', methods=['POST'])
@login_required
@admin_required
def reinstate_user(user_id):
    from billing import next_billing_date_from_today
    user = User.query.get_or_404(user_id)
    user.subscription_status    = 'active'
    user.cancellation_requested = False
    user.next_billing_date = next_billing_date_from_today()
    next_25 = user.next_billing_date
    db.session.commit()
    from log_utils import log_event
    log_event(current_user.email, 'billing_reinstated',
              detail=f'{user.email} reinstated manually by admin', user_id=user.id)
    flash(f'{user.name} reinstated. Next billing date: {next_25.strftime("%d %b %Y")}.', 'success')
    return redirect(url_for('admin_bp.user_detail', user_id=user_id))


@admin_bp.route('/admin/users/<int:user_id>/suspend', methods=['POST'])
@login_required
@admin_required
def suspend_user(user_id):
    """Manually suspend a user — sets subscription_status to cancelled."""
    user = User.query.get_or_404(user_id)
    user.subscription_status = 'cancelled'
    db.session.commit()
    from log_utils import log_event
    log_event(current_user.email, 'billing_suspended_manual',
              detail=f'{user.email} suspended manually by admin', user_id=user.id)
    flash(f'{user.name} has been suspended.', 'warning')
    return redirect(url_for('admin_bp.user_detail', user_id=user_id))


@admin_bp.route('/admin/users/<int:user_id>/reset-stripe', methods=['POST'])
@login_required
@admin_required
def reset_stripe_customer(user_id):
    """Clear the stored Stripe customer ID so a fresh one is created on next checkout."""
    user = User.query.get_or_404(user_id)
    old_id = user.stripe_customer_id
    user.stripe_customer_id = None
    db.session.commit()
    from log_utils import log_event
    log_event(current_user.email, 'stripe_id_reset',
              detail=f'{user.email} — cleared {old_id}', user_id=user.id)
    flash(f'Stripe customer ID cleared for {user.name}. A new one will be created on next checkout.', 'success')
    return redirect(url_for('admin_bp.user_detail', user_id=user_id))
