from flask import Blueprint, render_template
from flask_login import login_required, current_user
from models import db, UserFavouriteSpot, Spot, AdminSettings
from weather import get_day_summaries_for_user

main = Blueprint('main', __name__)


@main.route('/')
@login_required
def index():
    settings = AdminSettings.query.first()
    max_favs = settings.max_favourite_spots if settings else 3
    max_active = settings.max_active_spots if settings else 2

    # Get user's favourites for non-disabled spots only
    user_favs = (UserFavouriteSpot.query
                 .filter_by(user_id=current_user.id)
                 .join(Spot)
                 .filter(Spot.is_retired == False)
                 .all())

    active_favs = sorted([f for f in user_favs if f.is_active],     key=lambda f: f.spot.name)
    other_favs  = sorted([f for f in user_favs if not f.is_active], key=lambda f: f.spot.name)

    fav_count    = len(user_favs)
    active_count = len(active_favs)

    spot_summaries = {f.spot_id: get_day_summaries_for_user(f.spot_id, current_user) for f in user_favs}

    return render_template('dashboard.html',
                           active_favs=active_favs,
                           other_favs=other_favs,
                           fav_count=fav_count,
                           active_count=active_count,
                           max_favs=max_favs,
                           max_active=max_active,
                           at_max_favs=not current_user.is_admin and fav_count >= max_favs,
                           at_max_active=active_count >= max_active,
                           spot_summaries=spot_summaries)
