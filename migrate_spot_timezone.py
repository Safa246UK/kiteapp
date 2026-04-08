"""
One-off migration: add 'timezone' column to spot table and backfill all existing spots.
Run once: python migrate_spot_timezone.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db
from models import Spot
from timezonefinder import TimezoneFinder

tf = TimezoneFinder()

with app.app_context():
    # Add column if it doesn't exist yet (safe to run multiple times)
    with db.engine.connect() as conn:
        try:
            conn.execute(db.text("ALTER TABLE spot ADD COLUMN timezone VARCHAR(60)"))
            conn.commit()
            print("Column 'timezone' added to spot table.")
        except Exception as e:
            if 'already exists' in str(e).lower() or 'duplicate column' in str(e).lower():
                print("Column 'timezone' already exists — skipping ALTER.")
            else:
                raise

    # Backfill all spots that have no timezone set
    spots = Spot.query.all()
    updated = 0
    for spot in spots:
        if not spot.timezone:
            tz = tf.timezone_at(lat=spot.latitude, lng=spot.longitude) or 'Europe/London'
            spot.timezone = tz
            print(f"  {spot.name} ({spot.latitude:.4f}, {spot.longitude:.4f}) -> {tz}")
            updated += 1
        else:
            print(f"  {spot.name} — already has timezone: {spot.timezone}")

    db.session.commit()
    print(f"\nDone. {updated} spot(s) updated.")
