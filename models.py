from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Spot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    # Tide settings
    min_tide = db.Column(db.Float, default=0.0)
    max_tide = db.Column(db.Float, default=5.0)
    # Wind direction ratings (comma separated degrees e.g. "270,280,290")
    perfect_directions = db.Column(db.String(200), default='')
    good_directions = db.Column(db.String(200), default='')
    okay_directions = db.Column(db.String(200), default='')
    poor_directions = db.Column(db.String(200), default='')
    dangerous_directions = db.Column(db.String(200), default='')
    # Wind speed settings (knots)
    min_wind = db.Column(db.Float, default=12.0)
    max_wind = db.Column(db.Float, default=35.0)

class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    weight_kg = db.Column(db.Float, nullable=False)
    kite_size_adjustment = db.Column(db.Float, default=0.0)
    whatsapp_number = db.Column(db.String(20), nullable=False)
