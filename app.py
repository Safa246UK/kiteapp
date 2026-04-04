import os
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, send_from_directory
from flask_login import LoginManager
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
    with db.engine.connect() as conn:
        migrations = [
            "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS notification_type VARCHAR(10) DEFAULT 'push'",
            "ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS available_slots TEXT",
            "ALTER TABLE push_subscription ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
        ]
        for sql in migrations:
            try:
                conn.execute(db.text(sql))
            except Exception:
                pass
        conn.commit()

with app.app_context():
    db.create_all()
    from models import AdminSettings
    if not AdminSettings.query.first():
        db.session.add(AdminSettings())
        db.session.commit()
    run_migrations()

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

app.register_blueprint(auth)
app.register_blueprint(main)
app.register_blueprint(spots)
app.register_blueprint(admin_bp)
app.register_blueprint(push_bp)

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
