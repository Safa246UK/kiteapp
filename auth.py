from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, AdminSettings
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from extensions import bcrypt

auth = Blueprint('auth', __name__)


def _mail():
    from app import mail
    return mail


def generate_reset_token(email):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps(email, salt='password-reset')


def verify_reset_token(token, max_age=3600):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = s.loads(token, salt='password-reset', max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None
    return email


def generate_verify_token(email):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps(email, salt='email-verify')


def verify_email_token(token, max_age=86400):
    """Verify an email confirmation token. Valid for 24 hours."""
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = s.loads(token, salt='email-verify', max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None
    return email


def send_verification_email(user):
    token = generate_verify_token(user.email)
    verify_url = url_for('auth.verify_email', token=token, _external=True)
    msg = Message('WindChaser — Please verify your email address',
                  recipients=[user.email])
    msg.body = f"""Hi {user.first_name},

Welcome to WindChaser! Please verify your email address by clicking the link below:

{verify_url}

This link is valid for 24 hours. If you did not create an account, you can safely ignore this email.

— The WindChaser Team
"""
    msg.html = f"""
<p>Hi {user.first_name},</p>
<p>Welcome to WindChaser! Please verify your email address by clicking the button below:</p>
<p style="text-align:center; margin:2em 0;">
  <a href="{verify_url}"
     style="background:#0d6efd;color:white;padding:12px 28px;border-radius:6px;
            text-decoration:none;font-weight:bold;font-size:1rem;">
    ✅ Verify my email address
  </a>
</p>
<p>This link is valid for 24 hours. If you did not create an account, you can safely ignore this email.</p>
<p>— The WindChaser Team</p>
"""
    _mail().send(msg)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and bcrypt.check_password_hash(user.password, password):
            if not user.is_active:
                flash('Your account has been disabled. Please contact the admin.', 'danger')
                return redirect(url_for('auth.login'))
            if not user.email_verified:
                session['pending_verify_email'] = user.email
                flash('Please verify your email address before logging in. Check your inbox for the verification link.', 'warning')
                return redirect(url_for('auth.verify_pending'))
            login_user(user, remember=True)
            from log_utils import log_event
            log_event(user.email, 'login', user_id=user.id)
            return redirect(url_for('main.index'))
        flash('Invalid email or password.', 'danger')
    return render_template('auth/login.html')


@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        email      = request.form.get('email', '').strip().lower()
        first_name = request.form.get('first_name', '').strip()
        last_name  = request.form.get('last_name', '').strip()
        password   = request.form.get('password', '')
        confirm    = request.form.get('confirm_password', '')
        weight_kg          = float(request.form.get('weight_kg', 75.0))
        min_wind           = float(request.form.get('min_wind', 12.0))
        max_wind           = float(request.form.get('max_wind', 35.0))
        available_slots    = ','.join(request.form.getlist('available_slots'))
        whatsapp_dial_code = request.form.get('whatsapp_dial_code', '+44').strip()
        whatsapp_number    = request.form.get('whatsapp_number', '').strip() or None
        whatsapp_enabled   = 'whatsapp_enabled'  in request.form
        whatsapp_today     = 'whatsapp_today'     in request.form
        whatsapp_tomorrow  = 'whatsapp_tomorrow'  in request.form
        whatsapp_day_after = 'whatsapp_day_after' in request.form
        timezone           = request.form.get('timezone', 'Europe/London')
        notification_type  = request.form.get('notification_type', 'push')

        if not first_name or not last_name:
            flash('Please enter your first name and surname.', 'danger')
            return redirect(url_for('auth.register'))

        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('auth.register'))

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'danger')
            return redirect(url_for('auth.register'))

        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        is_first_user = User.query.count() == 0
        user = User(email=email, first_name=first_name, last_name=last_name,
                    password=hashed, is_admin=is_first_user,
                    email_verified=is_first_user,  # auto-verify the first (admin) user
                    weight_kg=weight_kg, min_wind=min_wind, max_wind=max_wind,
                    available_slots=available_slots or None,
                    whatsapp_dial_code=whatsapp_dial_code,
                    whatsapp_number=whatsapp_number,
                    whatsapp_enabled=whatsapp_enabled,
                    whatsapp_today=whatsapp_today,
                    whatsapp_tomorrow=whatsapp_tomorrow,
                    whatsapp_day_after=whatsapp_day_after,
                    timezone=timezone,
                    notification_type=notification_type)
        db.session.add(user)

        if is_first_user and not AdminSettings.query.first():
            db.session.add(AdminSettings())

        db.session.commit()

        if is_first_user:
            from log_utils import log_event
            log_event(email, 'register', detail='Admin account (auto-verified)', user_id=user.id)
            flash('Admin account created! Please log in.', 'success')
            return redirect(url_for('auth.login'))

        # Send verification email
        try:
            send_verification_email(user)
        except Exception as e:
            print(f"[Email] Verification send failed: {e}")
            flash('Account created but we could not send the verification email. Please contact windchaser@hamptons.me.uk.', 'warning')
            return redirect(url_for('auth.login'))

        from log_utils import log_event
        log_event(email, 'register', detail='Verification email sent', user_id=user.id)
        session['pending_verify_email'] = email
        return redirect(url_for('auth.verify_pending'))
    return render_template('auth/register.html')


@auth.route('/verify-pending')
def verify_pending():
    email = session.get('pending_verify_email')
    return render_template('auth/verify_pending.html', email=email)


@auth.route('/verify-email/<token>')
def verify_email(token):
    email = verify_email_token(token)
    if not email:
        flash('That verification link is invalid or has expired. Please request a new one.', 'danger')
        return redirect(url_for('auth.verify_pending'))
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Account not found.', 'danger')
        return redirect(url_for('auth.login'))
    if user.email_verified:
        flash('Your email is already verified. Please log in.', 'info')
        return redirect(url_for('auth.login'))
    user.email_verified = True
    db.session.commit()
    from log_utils import log_event
    log_event(user.email, 'email_verified', user_id=user.id)
    flash('✅ Email verified! Welcome to WindChaser — please log in.', 'success')
    return redirect(url_for('auth.login'))


@auth.route('/resend-verification', methods=['POST'])
def resend_verification():
    email = request.form.get('email', '').strip().lower() or session.get('pending_verify_email')
    if not email:
        flash('Could not determine your email address. Please register again.', 'danger')
        return redirect(url_for('auth.register'))
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('No account found with that email address.', 'danger')
        return redirect(url_for('auth.register'))
    if user.email_verified:
        flash('Your email is already verified. Please log in.', 'info')
        return redirect(url_for('auth.login'))
    try:
        send_verification_email(user)
        session['pending_verify_email'] = email
        from log_utils import log_event
        log_event(email, 'verification_resent', user_id=user.id)
        flash('Verification email resent — please check your inbox.', 'success')
    except Exception as e:
        print(f"[Email] Resend failed: {e}")
        flash('Could not send the email. Please try again or contact windchaser@hamptons.me.uk.', 'danger')
    return redirect(url_for('auth.verify_pending'))


@auth.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        # Always show the same message to avoid revealing whether email exists
        if user:
            token = generate_reset_token(email)
            reset_url = url_for('auth.reset_password', token=token, _external=True)
            msg = Message('WindChaser — Reset Your Password',
                          recipients=[email])
            msg.body = f"""Hi {user.name},

You requested a password reset for your WindChaser account.

Click the link below to set a new password (valid for 1 hour):
{reset_url}

If you did not request this, you can safely ignore this email.

— The WindChaser Team
"""
            try:
                _mail().send(msg)
                from log_utils import log_event
                log_event(email, 'password_reset_requested', user_id=user.id)
            except Exception:
                flash('Could not send email. Please contact the admin.', 'danger')
                return redirect(url_for('auth.forgot_password'))
        flash('If that email is registered, a reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot_password.html')


@auth.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    email = verify_reset_token(token)
    if not email:
        flash('That reset link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('auth/reset_password.html', token=token)
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/reset_password.html', token=token)
        user = User.query.filter_by(email=email).first()
        if user:
            user.password = bcrypt.generate_password_hash(password).decode('utf-8')
            db.session.commit()
            from log_utils import log_event
            log_event(user.email, 'password_reset', user_id=user.id)
            flash('Password updated! Please log in.', 'success')
            return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', token=token)


@auth.route('/profile')
@login_required
def profile():
    return redirect(url_for('admin_bp.user_detail', user_id=current_user.id))


@auth.route('/logout')
@login_required
def logout():
    from log_utils import log_event
    log_event(current_user.email, 'logout', user_id=current_user.id)
    logout_user()
    return redirect(url_for('auth.login'))
