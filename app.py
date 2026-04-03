import os
from dotenv import load_dotenv
load_dotenv()
from flask import Flask
from flask_login import LoginManager
from flask_mail import Mail
from models import db, User
from extensions import bcrypt

app = Flask(__name__)
_db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'kiteapp.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{_db_path}'
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

app.register_blueprint(auth)
app.register_blueprint(main)
app.register_blueprint(spots)
app.register_blueprint(admin_bp)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        from models import AdminSettings
        if not AdminSettings.query.first():
            db.session.add(AdminSettings())
            db.session.commit()

    # Start background scheduler (only in the main process, not the reloader)
    import os
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        from scheduler import start_scheduler, refresh_all_weather, refresh_all_tides, refresh_all_summaries
        start_scheduler()
        refresh_all_weather()
        refresh_all_tides()
        refresh_all_summaries()

    app.run(debug=True)
