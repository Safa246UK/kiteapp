from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# 16-point compass directions
COMPASS_POINTS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Kite profile
    weight_kg = db.Column(db.Float, default=80.0)
    kite_size_adjustment = db.Column(db.Float, default=0.0)  # +/- metres
    whatsapp_number = db.Column(db.String(20), nullable=True)

    # Availability
    available_days = db.Column(db.String(50), default='mon,tue,wed,thu,fri,sat,sun')
    available_from = db.Column(db.String(5), default='06:00')  # HH:MM
    available_to = db.Column(db.String(5), default='21:00')    # HH:MM

    # Relationships
    favourite_spots = db.relationship('UserFavouriteSpot', backref='user', lazy=True)
    notes = db.relationship('SpotNote', backref='author', lazy=True)


class Spot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, default='')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_retired = db.Column(db.Boolean, default=False)
    retired_at = db.Column(db.DateTime, nullable=True)

    # Tide settings (percentage of tidal range)
    # e.g. min_tide_percent=20 means "not usable below 20% of tidal range"
    # e.g. max_tide_percent=85 means "not usable above 85% of tidal range"
    min_tide_percent = db.Column(db.Float, default=20.0)
    max_tide_percent = db.Column(db.Float, default=85.0)

    # Wind speed settings (knots)
    min_wind = db.Column(db.Float, default=12.0)
    max_wind = db.Column(db.Float, default=35.0)

    # Wind direction ratings (comma separated compass points e.g. "SW,WSW,W")
    perfect_directions = db.Column(db.String(200), default='')
    good_directions = db.Column(db.String(200), default='')
    okay_directions = db.Column(db.String(200), default='')
    poor_directions = db.Column(db.String(200), default='')
    dangerous_directions = db.Column(db.String(200), default='')

    # Relationships
    favourited_by = db.relationship('UserFavouriteSpot', backref='spot', lazy=True)
    notes = db.relationship('SpotNote', backref='spot', lazy=True)


class UserFavouriteSpot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    spot_id = db.Column(db.Integer, db.ForeignKey('spot.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=False)  # Active = receives WhatsApp alerts
    added_at = db.Column(db.DateTime, default=datetime.utcnow)


class SpotNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    spot_id = db.Column(db.Integer, db.ForeignKey('spot.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    note = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AdminSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    max_favourite_spots = db.Column(db.Integer, default=3)
    max_active_spots = db.Column(db.Integer, default=2)
