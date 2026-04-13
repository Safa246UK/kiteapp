"""
reset_db.py — drop and recreate all WindChaser tables.

Run from the Render shell:
  python reset_db.py
"""

from app import app, db
from models import AdminSettings

with app.app_context():
    print("Dropping all tables...")
    db.drop_all()
    print("Recreating all tables...")
    db.create_all()
    print("Creating default AdminSettings...")
    db.session.add(AdminSettings())
    db.session.commit()
    print("Done. Database is clean. Register a new admin account to get started.")
