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
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Kite profile
    weight_kg = db.Column(db.Float, default=75.0)
    min_wind = db.Column(db.Float, default=12.0)   # knots — personal preference
    max_wind = db.Column(db.Float, default=35.0)   # knots — personal preference
    kite_size_adjustment = db.Column(db.Float, default=0.0)  # +/- metres
    whatsapp_dial_code  = db.Column(db.String(10),  default='+44')
    whatsapp_number     = db.Column(db.String(20),  nullable=True)
    whatsapp_enabled    = db.Column(db.Boolean,     default=False)
    whatsapp_today      = db.Column(db.Boolean,     default=True)
    whatsapp_tomorrow   = db.Column(db.Boolean,     default=False)
    whatsapp_day_after  = db.Column(db.Boolean,     default=False)
    timezone            = db.Column(db.String(50),  default='Europe/London')
    # How the user wants to receive alerts: 'push', 'whatsapp', 'both', 'none'
    notification_type   = db.Column(db.String(10),  default='push')

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}"

    # Availability — stored as comma-separated day_time slots e.g. "mon_morning,sat_afternoon"
    available_slots = db.Column(db.Text, default=','.join(
        f'{d}_{t}' for d in ['mon','tue','wed','thu','fri','sat','sun']
                   for t in ['morning','afternoon','evening']
    ))
    # Legacy columns retained so old references don't break
    available_days  = db.Column(db.String(50), default='mon,tue,wed,thu,fri,sat,sun')
    available_times = db.Column(db.String(50), default='morning,afternoon,evening')

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

    # Wind direction ratings (comma separated compass points e.g. "SW,WSW,W")
    perfect_directions = db.Column(db.String(200), default='')
    good_directions = db.Column(db.String(200), default='')
    okay_directions = db.Column(db.String(200), default='')
    poor_directions = db.Column(db.String(200), default='')
    dangerous_directions = db.Column(db.String(200), default='')

    # Timezone (IANA, auto-populated from coordinates via timezonefinder)
    timezone = db.Column(db.String(60), nullable=True)

    # Landlocked — tide data not relevant (lake, reservoir, etc.)
    is_landlocked = db.Column(db.Boolean, default=False)

    # Season window (optional — None = year-round)
    season_start_month = db.Column(db.Integer, nullable=True)  # 1=Jan … 12=Dec
    season_start_day   = db.Column(db.Integer, nullable=True)
    season_end_month   = db.Column(db.Integer, nullable=True)
    season_end_day     = db.Column(db.Integer, nullable=True)

    _MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun',
                    'Jul','Aug','Sep','Oct','Nov','Dec']

    @property
    def is_in_season(self):
        if self.season_start_month is None:
            return True
        from datetime import date
        today   = date.today()
        start   = (self.season_start_month, self.season_start_day)
        end     = (self.season_end_month,   self.season_end_day)
        current = (today.month, today.day)
        if start <= end:                          # e.g. Apr–Oct (no year wrap)
            return start <= current <= end
        return current >= start or current <= end  # e.g. Nov–Mar (wraps year)

    @property
    def season_label(self):
        if self.season_start_month is None:
            return None
        s = f"{self.season_start_day} {self._MONTH_NAMES[self.season_start_month - 1]}"
        e = f"{self.season_end_day} {self._MONTH_NAMES[self.season_end_month - 1]}"
        return f"{s} – {e}"

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


class TideCache(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    spot_id = db.Column(db.Integer, db.ForeignKey('spot.id'), nullable=False, unique=True)
    station_id = db.Column(db.String(20))
    station_name = db.Column(db.String(100))
    station_distance_km = db.Column(db.Float)
    station_hat = db.Column(db.Float, nullable=True)  # Highest Astronomical Tide (metres above Chart Datum)
    station_lat = db.Column(db.Float, nullable=True)  # Lowest Astronomical Tide (metres above Chart Datum)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    events_json = db.Column(db.Text)  # Raw high/low tide events from API


class WeatherCache(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    spot_id = db.Column(db.Integer, db.ForeignKey('spot.id'), nullable=False, unique=True)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    forecast_json = db.Column(db.Text)
    day_summary_json = db.Column(db.Text, nullable=True)  # {"2026-04-01": {"colour": "green", "hours": 5}, ...}


class PushSubscription(db.Model):
    """Stores a browser push subscription for a user (one per device)."""
    __tablename__ = 'push_subscription'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    endpoint   = db.Column(db.Text, nullable=False, unique=True)
    p256dh     = db.Column(db.Text, nullable=False)   # browser public key
    auth       = db.Column(db.Text, nullable=False)   # auth secret
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='push_subscriptions')


class AdminSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    max_favourite_spots = db.Column(db.Integer, default=3)
    max_active_spots = db.Column(db.Integer, default=2)
    default_min_tide_percent = db.Column(db.Float, default=0.0)
    default_max_tide_percent = db.Column(db.Float, default=90.0)
