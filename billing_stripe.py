"""
Stripe API calls for WindChaser billing.

Handles:
  - Customer creation (at registration)
  - Checkout sessions (card collection for trials, immediate charge for reactivation)
  - Off-session charges (25th monthly billing)
  - Webhook event processing
"""

import os
import stripe


def _s():
    """Return the stripe module with the secret key configured."""
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
    return stripe


def _meta_int(stripe_obj, key, default=0):
    """Safely read an integer from a Stripe object's metadata."""
    try:
        return int(stripe_obj.metadata[key])
    except (KeyError, TypeError, ValueError, AttributeError):
        return default


def _meta_str(stripe_obj, key, default=''):
    """Safely read a string from a Stripe object's metadata."""
    try:
        return str(stripe_obj.metadata[key])
    except (KeyError, TypeError, AttributeError):
        return default


def _price_id():
    return os.environ.get('STRIPE_PRICE_ID', '')


# ---------------------------------------------------------------------------
# Customer management
# ---------------------------------------------------------------------------

def create_stripe_customer(user):
    """Create a Stripe Customer for a new user and store the ID.

    Safe to call if the user already has a stripe_customer_id — returns
    the existing ID without creating a duplicate.
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = _s().Customer.create(
        email=user.email,
        name=user.name,
        metadata={'user_id': str(user.id)},
    )
    from models import db
    user.stripe_customer_id = customer.id
    db.session.commit()
    return customer.id


def _ensure_customer(user):
    """Make sure the user has a valid Stripe customer, creating one if needed.

    Also handles the case where the customer was deleted from Stripe —
    clears the stale ID and creates a fresh one.
    """
    from models import db
    if not user.stripe_customer_id:
        create_stripe_customer(user)
        return
    # Verify the customer still exists in Stripe
    try:
        _s().Customer.retrieve(user.stripe_customer_id)
    except stripe.error.InvalidRequestError:
        # Customer was deleted from Stripe — create a fresh one
        user.stripe_customer_id = None
        db.session.commit()
        create_stripe_customer(user)


def set_default_payment_method(stripe_customer_id, payment_method_id):
    """Attach a payment method to a customer and set it as the default."""
    _s().PaymentMethod.attach(payment_method_id, customer=stripe_customer_id)
    _s().Customer.modify(
        stripe_customer_id,
        invoice_settings={'default_payment_method': payment_method_id},
    )


def get_default_payment_method(stripe_customer_id):
    """Return the default payment method ID for a customer, or None."""
    customer = _s().Customer.retrieve(stripe_customer_id)
    return (customer.get('invoice_settings') or {}).get('default_payment_method')


# ---------------------------------------------------------------------------
# Checkout sessions
# ---------------------------------------------------------------------------

def create_setup_checkout_url(user, success_url, cancel_url):
    """Return a Stripe Checkout URL in setup mode (saves card, no charge).

    Used when a trial user clicks 'Add payment details'.
    """
    _ensure_customer(user)

    session = _s().checkout.Session.create(
        customer=user.stripe_customer_id,
        mode='setup',
        success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=cancel_url,
        metadata={'user_id': str(user.id), 'purpose': 'setup'},
    )
    return session.url


def create_payment_checkout_url(user, success_url, cancel_url):
    """Return a Stripe Checkout URL in payment mode (charges £3 immediately).

    Used for reactivation — the catch-up payment for the current month.
    """
    _ensure_customer(user)

    session = _s().checkout.Session.create(
        customer=user.stripe_customer_id,
        mode='payment',
        line_items=[{'price': _price_id(), 'quantity': 1}],
        success_url=success_url + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=cancel_url,
        metadata={'user_id': str(user.id), 'purpose': 'reactivation'},
    )
    return session.url


# ---------------------------------------------------------------------------
# Off-session charging (25th monthly billing)
# ---------------------------------------------------------------------------

def charge_customer(user):
    """Charge a customer £3.00 using their saved default payment method.

    Called by the cron on the 25th for trial-ending and active users.
    Returns (success: bool, detail: str).
    """
    if not user.stripe_customer_id:
        return False, 'No Stripe customer ID'

    pm_id = get_default_payment_method(user.stripe_customer_id)
    if not pm_id:
        return False, 'No payment method on file'

    try:
        intent = _s().PaymentIntent.create(
            amount=300,  # £3.00 in pence
            currency='gbp',
            customer=user.stripe_customer_id,
            payment_method=pm_id,
            off_session=True,
            confirm=True,
            description=f'WindChaser monthly subscription',
            metadata={'user_id': str(user.id)},
        )
        return True, intent.id
    except stripe.error.CardError as e:
        return False, e.user_message or str(e)
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Webhook event processing
# ---------------------------------------------------------------------------

def handle_webhook_event(payload, sig_header):
    """Verify and process a Stripe webhook event.

    Returns (ok: bool, message: str).
    """
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

    try:
        event = _s().Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        return False, 'Invalid signature'
    except Exception as e:
        return False, str(e)

    etype = event.type
    obj   = event.data.object

    try:
        if etype == 'checkout.session.completed':
            _on_checkout_completed(obj)
        elif etype == 'payment_intent.succeeded':
            _on_payment_succeeded(obj)
        elif etype == 'payment_intent.payment_failed':
            _on_payment_failed(obj)
    except Exception as e:
        import traceback
        from log_utils import log_event
        log_event('STRIPE', 'webhook_handler_error',
                  detail=f'{etype} — {e}\n{traceback.format_exc()}')
        return False, f'Handler error: {e}'

    return True, etype


def _on_checkout_completed(session):
    """Handle a completed Checkout session."""
    from models import db, User
    from log_utils import log_event

    user_id = _meta_int(session, 'user_id')
    purpose = _meta_str(session, 'purpose')
    mode    = session.mode

    user = User.query.get(user_id)
    if not user:
        return

    if mode == 'setup':
        # Card saved — attach as default payment method so we can charge on the 25th
        setup_intent_id = session.setup_intent
        if setup_intent_id:
            si    = _s().SetupIntent.retrieve(setup_intent_id)
            pm_id = si.payment_method
            if pm_id and user.stripe_customer_id:
                set_default_payment_method(user.stripe_customer_id, pm_id)
                log_event('STRIPE', 'card_saved',
                          detail=f'{user.email} saved card via Checkout', user_id=user.id)

    elif mode == 'payment' and purpose == 'reactivation':
        # Reactivation payment succeeded — reinstate account
        from billing import advance_billing_date
        from datetime import date
        today = date.today()
        next_25 = date(today.year, today.month, 25)
        if today.day >= 25:
            next_25 = advance_billing_date(next_25)
        user.subscription_status    = 'active'
        user.cancellation_requested = False
        user.next_billing_date      = next_25
        db.session.commit()
        log_event('STRIPE', 'reactivation_paid',
                  detail=f'{user.email} reactivated via Checkout', user_id=user.id)


def _on_payment_succeeded(intent):
    """Handle a successful off-session PaymentIntent (25th billing)."""
    from models import db, User
    from billing import advance_billing_date
    from log_utils import log_event

    user_id = _meta_int(intent, 'user_id')
    user = User.query.get(user_id)
    if not user:
        return

    from datetime import date
    today = date.today()
    next_25 = date(today.year, today.month, 25)
    if today.day >= 25:
        next_25 = advance_billing_date(next_25)

    user.subscription_status = 'active'
    user.next_billing_date   = next_25
    db.session.commit()
    log_event('STRIPE', 'payment_succeeded',
              detail=f'{user.email} — £3.00 charged successfully', user_id=user.id)


def _on_payment_failed(intent):
    """Handle a failed off-session PaymentIntent (25th billing)."""
    from models import db, User
    from log_utils import log_event

    user_id = _meta_int(intent, 'user_id')
    user = User.query.get(user_id)
    if not user:
        return

    user.subscription_status = 'unpaid'
    db.session.commit()

    from billing_emails import send_payment_failed_email
    app_url = os.environ.get('APP_URL', '')
    send_payment_failed_email(user, app_url)
    log_event('STRIPE', 'payment_failed',
              detail=f'{user.email} — charge failed', user_id=user.id)
