from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(timezone='Europe/London')


def refresh_all_weather():
    """Fetch and cache weather for every active spot. Returns (ok, failed) counts.

    Uses ThreadPoolExecutor so spots are fetched in parallel (up to 3 at a time).
    Each thread gets its own Flask app context so SQLAlchemy sessions are thread-safe.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app import app
    from models import Spot
    from weather import fetch_and_cache_weather
    from log_utils import log_event

    # Collect spot data inside a single context, then release it before spawning threads
    with app.app_context():
        spot_data = [(s.id, s.name) for s in Spot.query.filter_by(is_retired=False).all()]

    def fetch_one(spot_id, spot_name):
        with app.app_context():
            try:
                spot = Spot.query.get(spot_id)
                fetch_and_cache_weather(spot)
                log_event('CRON', 'weather_fetch', detail=f"{spot_name} — success", spot_id=spot_id)
                print(f"[Weather] Updated: {spot_name}")
                return True, spot_name, None
            except Exception as e:
                log_event('CRON', 'weather_fetch', detail=f"{spot_name} — FAILED: {e}", spot_id=spot_id)
                print(f"[Weather] Failed for {spot_name}: {e}")
                return False, spot_name, str(e)

    ok, failed = 0, 0
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_one, sid, name): name for sid, name in spot_data}
        for future in as_completed(futures):
            success, _, _ = future.result()
            if success:
                ok += 1
            else:
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
