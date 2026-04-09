"""
push.py — Web Push notification blueprint and send helper.

Routes:
  GET  /push/vapid-public-key   → returns VAPID public key for client subscription
  POST /push/subscribe          → saves a push subscription for the current user
  POST /push/unsubscribe        → removes a push subscription
  POST /admin/push/test         → admin test: send a push to a specific user

Helper:
  send_push_to_user(user, title, body, url) → (success, detail)
"""

import os
import json
import logging
from flask import Blueprint, request, jsonify, make_response
from flask_login import login_required, current_user
from models import db, PushSubscription
from pywebpush import webpush, WebPushException

push_bp = Blueprint('push', __name__)
log = logging.getLogger(__name__)


def _private_key():
    """Return VAPID private key as a base64url SEC1 DER string.

    py_vapid's Vapid.from_string() accepts this format natively —
    no PEM headers, no newlines, no encoding ambiguity.
    """
    return os.environ.get('VAPID_PRIVATE_KEY', '').strip()


def _public_key():
    return os.environ.get('VAPID_PUBLIC_KEY', '')


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@push_bp.route('/push/vapid-public-key')
def vapid_public_key():
    """Return the VAPID public key so the browser can create a subscription."""
    return jsonify({'publicKey': _public_key()})


@push_bp.route('/push/subscribe', methods=['POST'])
@login_required
def subscribe():
    """Save (or update) a push subscription for the logged-in user."""
    data     = request.get_json() or {}
    endpoint = data.get('endpoint')
    p256dh   = (data.get('keys') or {}).get('p256dh')
    auth     = (data.get('keys') or {}).get('auth')

    if not all([endpoint, p256dh, auth]):
        return jsonify({'error': 'Missing subscription fields'}), 400

    sub = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if not sub:
        sub = PushSubscription(user_id=current_user.id, endpoint=endpoint)
        db.session.add(sub)
    sub.user_id = current_user.id
    sub.p256dh  = p256dh
    sub.auth    = auth
    db.session.commit()

    from log_utils import log_event
    log_event(current_user.email, 'push_subscribed',
              detail='Push subscription saved', user_id=current_user.id)

    # Set a long-lived server cookie so the dashboard knows this device is
    # subscribed — avoids the JS race condition where Notification.permission
    # returns 'default' on cold app start before Chrome re-connects to FCM.
    resp = make_response(jsonify({'status': 'ok'}))
    resp.set_cookie(
        'wc_push', '1',
        max_age=365 * 24 * 60 * 60,   # 1 year
        samesite='Lax',
        secure=True,
        httponly=False,                 # JS doesn't need it; server reads it
    )
    return resp


@push_bp.route('/push/unsubscribe', methods=['POST'])
@login_required
def unsubscribe():
    """Remove a push subscription."""
    data     = request.get_json() or {}
    endpoint = data.get('endpoint')
    if endpoint:
        PushSubscription.query.filter_by(
            user_id=current_user.id, endpoint=endpoint
        ).delete()
        db.session.commit()
        from log_utils import log_event
        log_event(current_user.email, 'push_unsubscribed',
                  detail='Push subscription removed', user_id=current_user.id)
    return jsonify({'status': 'ok'})


# ---------------------------------------------------------------------------
# Send helper (used by alerts.py)
# ---------------------------------------------------------------------------

def send_push_to_user(user, title, body, url='/'):
    """
    Send a push notification to all of a user's subscribed devices.
    Automatically removes expired (410 Gone) subscriptions.
    Returns (success: bool, detail: str).
    """
    private_key = _private_key()
    public_key  = _public_key()

    if not private_key or not public_key:
        return False, 'VAPID keys not configured'

    subs = PushSubscription.query.filter_by(user_id=user.id).all()
    if not subs:
        return False, 'No push subscriptions for user'

    payload = json.dumps({'title': title, 'body': body, 'url': url})
    sent, errors = 0, []

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={'sub': 'mailto:admin@windchaser.com'},
                headers={'Urgency': 'high'},
                ttl=3600,   # keep in push server queue for up to 1 hour if device offline
            )
            sent += 1
        except WebPushException as e:
            if e.response is not None and e.response.status_code == 410:
                # Subscription has expired — clean it up
                db.session.delete(sub)
                db.session.commit()
            else:
                errors.append(str(e))
                log.warning('Push failed for user %s: %s', user.id, e)
        except Exception as e:
            errors.append(str(e))
            log.warning('Push error for user %s: %s', user.id, e)

    if sent:
        return True, f'{sent} device(s) notified'
    return False, '; '.join(errors) or 'No devices notified'


def send_push_all(title, body, url='/'):
    """Send a push notification to every subscribed user."""
    subs = PushSubscription.query.all()
    user_ids = {s.user_id for s in subs}
    results = []
    for uid in user_ids:
        from models import User
        user = User.query.get(uid)
        if user and user.is_active:
            ok, detail = send_push_to_user(user, title, body, url)
            results.append((user, ok, detail))
    return results
