import os
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, send_from_directory, render_template, make_response, redirect, url_for, request
from flask_login import LoginManager, current_user
from flask_mail import Mail
from models import db, User
from extensions import bcrypt

app = Flask(__name__)

# Use PostgreSQL if DATABASE_URL is set (production), otherwise SQLite (local dev)
_db_url = os.environ.get('DATABASE_URL')
if _db_url:
    # Render sometimes provides postgres:// — SQLAlchemy requires postgresql://
    if _db_url.startswith('postgres://'):
        _db_url = _db_url.replace('postgres://', 'postgresql://', 1)
else:
    _db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'kiteapp.db')
    _db_url = f'sqlite:///{_db_path}'
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,   # test connections before use, discard stale ones
    'pool_recycle': 280,     # recycle connections every 4.5 min (before Render's 5 min idle timeout)
}
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-later')

# Mail config
app.config['MAIL_SERVER']          = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT']            = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS']         = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME']        = os.environ.get('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD']        = os.environ.get('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER']  = os.environ.get('MAIL_DEFAULT_SENDER', '')

db.init_app(app)
bcrypt.init_app(app)
mail = Mail(app)

def run_migrations():
    """Add any missing columns to existing tables (safe to run on every startup)."""
    migrations = [
        ("user", "notification_type", "VARCHAR(10) DEFAULT 'push'"),
        ("user", "available_slots",   "TEXT"),
        ("push_subscription", "created_at", "TIMESTAMP"),
        ("user", "email_verified",       "BOOLEAN DEFAULT TRUE"),  # existing users pre-verified
        ("spot", "timezone",             "VARCHAR(60)"),
        # Billing
        ("user", "subscription_status",    "VARCHAR(20) DEFAULT 'trial'"),
        ("user", "first_billing_date",     "DATE"),
        ("user", "next_billing_date",      "DATE"),
        ("user", "cancellation_requested", "BOOLEAN DEFAULT FALSE"),
        ("user", "is_free_for_life",       "BOOLEAN DEFAULT FALSE"),
        ("user", "stripe_customer_id",     "VARCHAR(50)"),
        ("admin_settings", "billing_enabled", "BOOLEAN DEFAULT FALSE"),
    ]
    is_postgres = 'postgresql' in str(db.engine.url)
    with db.engine.connect() as conn:
        for table, column, col_type in migrations:
            # Check if column already exists (syntax differs between DBs)
            if is_postgres:
                exists = conn.execute(db.text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name=:t AND column_name=:c"
                ), {"t": table, "c": column}).fetchone()
            else:
                # SQLite: use PRAGMA table_info
                rows = conn.execute(db.text(f'PRAGMA table_info("{table}")')).fetchall()
                exists = any(row[1] == column for row in rows)
            if not exists:
                try:
                    conn.execute(db.text(
                        f'ALTER TABLE "{table}" ADD COLUMN {column} {col_type}'
                    ))
                    conn.commit()
                except Exception as e:
                    print(f"Migration warning ({table}.{column}): {e}")

with app.app_context():
    db.create_all()
    run_migrations()  # add missing columns before any queries touch the schema
    from models import AdminSettings
    if not AdminSettings.query.first():
        db.session.add(AdminSettings())
        db.session.commit()

login_manager = LoginManager(app)
login_manager.login_view = 'auth.login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Register blueprints
from auth import auth
from main import main
from spots import spots
from admin import admin_bp
from push import push_bp
from billing_routes import billing_bp

app.register_blueprint(auth)
app.register_blueprint(main)
app.register_blueprint(spots)
app.register_blueprint(admin_bp)
app.register_blueprint(push_bp)
app.register_blueprint(billing_bp)

# ---------------------------------------------------------------------------
# Billing gate — runs on every authenticated request
# ---------------------------------------------------------------------------

_BILLING_SKIP = {
    None, 'static', 'sw', 'manifest', 'welcome',
    'auth.login', 'auth.logout', 'auth.register',
    'auth.verify_email', 'auth.verify_pending', 'auth.resend_verification',
    'auth.forgot_password', 'auth.reset_password',
    'billing.suspended', 'billing.cancel_confirm', 'billing.cancel_confirm_post',
    'billing.revert_cancel',
    'billing.add_payment', 'billing.reactivate',
    'billing.checkout_success', 'billing.checkout_cancel',
    'billing.stripe_webhook',
}

@app.before_request
def billing_gate():
    if not current_user.is_authenticated:
        return
    if request.endpoint in _BILLING_SKIP:
        return
    if current_user.is_admin:
        return  # admins always get through
    settings = AdminSettings.query.first()
    if not settings or not settings.billing_enabled:
        return
    from billing import is_access_allowed
    if not is_access_allowed(current_user, billing_enabled=True):
        if current_user.subscription_status == 'cancelled':
            return redirect(url_for('billing.suspended'))
        # 'unpaid' — let them in but the red banner will show (via context processor)


@app.context_processor
def billing_context():
    """Inject billing_unpaid flag into all templates."""
    if not current_user.is_authenticated or current_user.is_admin:
        return {}
    settings = AdminSettings.query.first()
    if not settings or not settings.billing_enabled:
        return {}
    if current_user.subscription_status == 'unpaid':
        return {'billing_unpaid': True}
    return {}


# Welcome / splash page — shown automatically on first visit, also linked as Help
@app.route('/welcome')
def welcome():
    resp = make_response(render_template('welcome.html'))
    resp.set_cookie('seen_welcome', '1', max_age=60*60*24*365)  # remember for 1 year
    return resp


# Log every authenticated page view (GET requests only, excluding noise)
_PAGE_VIEW_SKIP = {
    None, 'static', 'sw', 'manifest',          # infrastructure
    'push.vapid_public_key', 'spots.api_all',   # JSON APIs
    'push.subscribe', 'push.unsubscribe',        # already specifically logged
    'spots.detail',                              # already logged as spot_viewed
    'admin_bp.logs',                             # don't log the log page itself
}

@app.before_request
def log_page_view():
    if request.method != 'GET':
        return
    if not current_user.is_authenticated:
        return
    if request.endpoint in _PAGE_VIEW_SKIP:
        return
    import re
    detail = request.path
    # Resolve /admin/users/<id> to the user's email address
    m = re.match(r'^/admin/users/(\d+)$', request.path)
    if m:
        u = User.query.get(int(m.group(1)))
        if u:
            detail = f'/admin/users/{u.email}'
    from log_utils import log_event
    log_event(current_user.email, 'page_view',
              detail=detail, user_id=current_user.id)


# Redirect first-time visitors to welcome BEFORE Flask-Login can flash "please log in"
@app.before_request
def redirect_first_time_visitors():
    # Skip: already seen welcome, or static/infrastructure endpoints
    if request.cookies.get('seen_welcome'):
        return
    skip_endpoints = {None, 'static', 'sw', 'manifest', 'welcome', 'admin_bp.refresh_weather',
                      'auth.verify_email', 'auth.verify_pending', 'auth.resend_verification',
                      'auth.reset_password', 'auth.forgot_password', 'auth.login', 'auth.register',
                      'billing.stripe_webhook'}
    if request.endpoint in skip_endpoints:
        return
    # Logged-in users never need the welcome detour
    if current_user.is_authenticated:
        return
    return redirect(url_for('welcome'))

# Serve service worker from root so it has full scope
@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

if __name__ == '__main__':
    # Start background scheduler (only in the main process, not the reloader)
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        from scheduler import start_scheduler, refresh_all_weather, refresh_all_tides, refresh_all_summaries
        start_scheduler()
        refresh_all_weather()
        refresh_all_tides()
        refresh_all_summaries()

    app.run(debug=True)
