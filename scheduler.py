from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(timezone='Europe/London')


def refresh_all_weather():
    """Fetch and cache weather for every active spot. Returns (ok, failed) counts."""
    from app import app
    from models import Spot
    from weather import fetch_and_cache_weather
    from log_utils import log_event

    ok, failed = 0, 0
    with app.app_context():
        spots = Spot.query.filter_by(is_retired=False).all()
        for spot in spots:
            try:
                fetch_and_cache_weather(spot)
                print(f"[Weather] Updated: {spot.name}")
                log_event('CRON', 'weather_fetch', detail=f"{spot.name} — success", spot_id=spot.id)
                ok += 1
            except Exception as e:
                print(f"[Weather] Failed for {spot.name}: {e}")
                log_event('CRON', 'weather_fetch', detail=f"{spot.name} — FAILED: {e}", spot_id=spot.id)
                failed += 1
    return ok, failed


def refresh_all_tides():
    """Fetch and cache tide data for every active spot, at most once per 24 hours.
    Returns (ok, skipped, failed) counts."""
    import os
    from datetime import datetime, timedelta
    from app import app
    from models import Spot, TideCache
    from tides import fetch_and_cache_tides

    api_key = os.environ.get('ADMIRALTY_API_KEY', '')
    if not api_key:
        print("[Tides] No ADMIRALTY_API_KEY set — skipping tide refresh")
        return 0, 0, 0

    cutoff = datetime.utcnow() - timedelta(hours=24)
    ok, skipped, failed = 0, 0, 0

    with app.app_context():
        from log_utils import log_event
        spots = Spot.query.filter_by(is_retired=False).all()
        for spot in spots:
            cache = TideCache.query.filter_by(spot_id=spot.id).first()
            if cache and cache.fetched_at and cache.fetched_at > cutoff:
                print(f"[Tides] Skipping {spot.name} — cache is less than 24h old")
                log_event('CRON', 'tide_fetch', detail=f"{spot.name} — skipped (cache < 24h old)", spot_id=spot.id)
                skipped += 1
                continue
            try:
                fetch_and_cache_tides(spot, api_key)
                print(f"[Tides] Updated: {spot.name}")
                log_event('CRON', 'tide_fetch', detail=f"{spot.name} — success", spot_id=spot.id)
                ok += 1
            except Exception as e:
                print(f"[Tides] Failed for {spot.name}: {e}")
                log_event('CRON', 'tide_fetch', detail=f"{spot.name} — FAILED: {e}", spot_id=spot.id)
                failed += 1
    return ok, skipped, failed


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
