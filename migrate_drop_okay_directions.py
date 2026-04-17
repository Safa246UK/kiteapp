"""
migrate_drop_okay_directions.py

Drops the now-unused okay_directions column from the spot table.

Run from the Render shell ONCE after deploying this change:
    python migrate_drop_okay_directions.py
"""

from app import app, db

with app.app_context():
    try:
        db.session.execute(db.text('ALTER TABLE spot DROP COLUMN IF EXISTS okay_directions'))
        db.session.commit()
        print("Done — okay_directions column removed from spot table.")
    except Exception as e:
        db.session.rollback()
        print(f"Error: {e}")
