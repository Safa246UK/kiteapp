"""
Centralised logging helper for WindChaser.

Usage:
    from log_utils import log_event
    log_event('ken@hamptons.me.uk', 'login')
    log_event('CRON', 'weather_fetch', detail='Marske — success', spot_id=3)

Never raises — logging must never break the operation being logged.
"""
import os
from datetime import datetime, timedelta


def log_event(actor, event_type, detail=None, spot_id=None, user_id=None):
    """Write a single entry to AppLog."""
    try:
        from models import db, AppLog
        entry = AppLog(
            actor=str(actor),
            event_type=str(event_type),
            detail=detail,
            spot_id=spot_id,
            user_id=user_id,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as e:
        print(f"[Log] Failed to write log entry ({event_type}): {e}")
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass


def purge_old_logs():
    """Delete log entries older than LOG_RETENTION_DAYS (default 999)."""
    try:
        retention_days = int(os.environ.get('LOG_RETENTION_DAYS', 999))
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        from models import db, AppLog
        deleted = AppLog.query.filter(AppLog.timestamp < cutoff).delete()
        db.session.commit()
        if deleted:
            print(f"[Log] Purged {deleted} log entries older than {retention_days} days")
    except Exception as e:
        print(f"[Log] Purge failed: {e}")
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass
