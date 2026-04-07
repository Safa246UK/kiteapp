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
    """Fetch and cache tide data for every active spot, at most once per 24 hours."""
    import os
    from datetime import datetime, timedelta
    from app import app
    from models import Spot, TideCache
    from tides import fetch_and_cache_tides

    api_key = os.environ.get('ADMIRALTY_API_KEY', '')
    if not api_key:
        print("[Tides] No ADMIRALTY_API_KEY set — skipping tide refresh")
        return

    cutoff = datetime.utcnow() - timedelta(hours=24)

    with app.app_context():
        spots = Spot.query.filter_by(is_retired=False).all()
        for spot in spots:
            cache = TideCache.query.filter_by(spot_id=spot.id).first()
            if cache and cache.fetched_at and cache.fetched_at > cutoff:
                print(f"[Tides] Skipping {spot.name} — cache is less than 24h old")
                continue
            try:
                fetch_and_cache_tides(spot, api_key)
                print(f"[Tides] Updated: {spot.name}")
            except Exception as e:
                print(f"[Tides] Failed for {spot.name}: {e}")


def refresh_all_summaries():
    """Compute and cache day condition summaries for every active spot."""
    from app import app
    from models import Spot
    from weather import compute_and_cache_summary

    with app.app_context():
        spots = Spot.query.filter_by(is_retired=False).all()
        for spot in spots:
            try:
                compute_and_cache_summary(spot)
            except Exception as e:
                print(f"[Summaries] Failed for {spot.name}: {e}")


def start_scheduler():
    scheduler.add_job(
        refresh_all_weather,
        trigger='interval',
        hours=1,
        id='refresh_weather',
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_all_summaries,
        trigger='interval',
        hours=1,
        id='refresh_summaries',
        replace_existing=True,
    )
    scheduler.start()
    print("[Scheduler] Started — weather and summaries refresh every hour.")
