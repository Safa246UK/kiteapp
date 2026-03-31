from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(timezone='Europe/London')


def refresh_all_weather():
    """Fetch and cache weather for every active spot."""
    from app import app
    from models import Spot
    from weather import fetch_and_cache_weather

    with app.app_context():
        spots = Spot.query.filter_by(is_retired=False).all()
        for spot in spots:
            try:
                fetch_and_cache_weather(spot)
                print(f"[Weather] Updated: {spot.name}")
            except Exception as e:
                print(f"[Weather] Failed for {spot.name}: {e}")


def refresh_all_tides():
    """Fetch and cache tide data for every active spot."""
    import os
    from app import app
    from models import Spot
    from tides import fetch_and_cache_tides

    api_key = os.environ.get('ADMIRALTY_API_KEY', '')
    if not api_key:
        print("[Tides] No ADMIRALTY_API_KEY set — skipping tide refresh")
        return

    with app.app_context():
        spots = Spot.query.filter_by(is_retired=False).all()
        for spot in spots:
            try:
                fetch_and_cache_tides(spot, api_key)
            except Exception as e:
                print(f"[Tides] Failed for {spot.name}: {e}")


def start_scheduler():
    scheduler.add_job(
        refresh_all_weather,
        trigger='interval',
        hours=1,
        id='refresh_weather',
        replace_existing=True,
    )
    scheduler.start()
    print("[Scheduler] Started — weather refreshes every hour.")
