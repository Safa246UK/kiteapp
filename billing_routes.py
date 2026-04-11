"""
Billing-related routes for WindChaser.

Covers the full billing flow:
  - Suspended screen
  - Cancellation / revert-cancel
  - Stripe Checkout (setup mode for card collection, payment mode for reactivation)
  - Stripe webhook endpoint
"""

import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from models import db

billing_bp = Blueprint('billing', __name__)


@billing_bp.route('/billing/suspended')
@login_required
def suspended():
    """Shown to users whose account has been suspended (subscription_status='cancelled')."""
    return render_template('billing/suspended.html')


@billing_bp.route('/billing/cancel', methods=['GET'])
@login_required
def cancel_confirm():
    """Cancellation confirmation page — shown when user clicks 'Cancel my membership'."""
    return render_template('billing/cancel_confirm.html')


@billing_bp.route('/billing/cancel', methods=['POST'])
@login_required
def cancel_confirm_post():
    """Process the cancellation — sets cancellation_requested flag."""
    current_user.cancellation_requested = True
    db.session.commit()
    from log_utils import log_event
    log_event(current_user.email, 'billing_cancel_requested',
              detail='User requested cancellation', user_id=current_user.id)
    flash('Your subscription has been cancelled. You keep full access until the 1st of next month.', 'info')
    return redirect(url_for('main.index'))


@billing_bp.route('/billing/revert-cancel', methods=['POST'])
@login_required
def revert_cancel():
    """Allow a user to un-cancel before the 1st (from their profile page)."""
    current_user.cancellation_requested = False
    db.session.commit()
    from log_utils import log_event
    log_event(current_user.email, 'billing_cancel_reverted',
              detail='User reinstated subscription', user_id=current_user.id)
    flash('Cancellation reversed — your subscription will continue. Thank you! 🪁', 'success')
    return redirect(url_for('main.index'))


# ---------------------------------------------------------------------------
# Stripe Checkout routes
# ---------------------------------------------------------------------------

@billing_bp.route('/billing/add-payment')
@login_required
def add_payment():
    """Redirect to Stripe Checkout (setup mode) to collect card details.

    Used by trial users clicking 'Add payment details' in the warning email
    or the unpaid banner.
    """
    from billing_stripe import create_setup_checkout_url
    app_url = os.environ.get('APP_URL', request.host_url.rstrip('/'))
    success_url = app_url + url_for('billing.checkout_success')
    cancel_url  = app_url + url_for('billing.checkout_cancel')
    try:
        checkout_url = create_setup_checkout_url(current_user, success_url, cancel_url)
        return redirect(checkout_url)
    except Exception as e:
        current_app.logger.error(f'Stripe setup checkout error: {e}')
        flash('Sorry, we could not connect to the payment provider. Please try again later.', 'danger')
        return redirect(url_for('main.index'))


@billing_bp.route('/billing/reactivate')
@login_required
def reactivate():
    """Redirect to Stripe Checkout (payment mode) to pay £3 and reactivate.

    Used by suspended users.
    """
    from billing_stripe import create_payment_checkout_url
    app_url = os.environ.get('APP_URL', request.host_url.rstrip('/'))
    success_url = app_url + url_for('billing.checkout_success')
    cancel_url  = app_url + url_for('billing.checkout_cancel')
    try:
        checkout_url = create_payment_checkout_url(current_user, success_url, cancel_url)
        return redirect(checkout_url)
    except Exception as e:
        current_app.logger.error(f'Stripe payment checkout error: {e}')
        flash('Sorry, we could not connect to the payment provider. Please try again later.', 'danger')
        return redirect(url_for('billing.suspended'))


@billing_bp.route('/billing/checkout-success')
@login_required
def checkout_success():
    """Landing page after a successful Stripe Checkout session."""
    return render_template('billing/checkout_success.html')


@billing_bp.route('/billing/checkout-cancel')
@login_required
def checkout_cancel():
    """Landing page when a user cancels out of Stripe Checkout."""
    return render_template('billing/checkout_cancel.html')


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------

@billing_bp.route('/billing/webhook', methods=['POST'])
def stripe_webhook():
    """Receive and process Stripe webhook events.

    Must NOT require login — Stripe calls this directly.
    """
    payload    = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')

    from billing_stripe import handle_webhook_event
    ok, message = handle_webhook_event(payload, sig_header)

    if not ok:
        current_app.logger.warning(f'Stripe webhook rejected: {message}')
        return {'error': message}, 400

    return {'status': 'ok', 'event': message}, 200
