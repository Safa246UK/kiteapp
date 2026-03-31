import os
from flask import Flask
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_mail import Mail
from models import db, User

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///kiteapp.db'
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
bcrypt = Bcrypt(app)
mail = Mail(app)

login_manager = LoginManager(app)
login_manager.login_view = 'auth.login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Register blueprints
from auth import auth, bcrypt as auth_bcrypt
from main import main
from spots import spots
from admin import admin_bp, bcrypt as admin_bcrypt

auth_bcrypt.init_app(app)
admin_bcrypt.init_app(app)
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
    app.run(debug=True)
