"""
Billing email functions for WindChaser.

Sends the three billing-related emails described in the spec:
  - Trial ending warning  (22nd, to users whose first payment is due on the 25th)
  - Renewal warning       (22nd, to existing paying subscribers)
  - Payment failed        (25th, when a card charge fails or no card is on file)

Payment links are placeholders until Stripe is integrated.
"""

from datetime import date, datetime


def _mail():
    from app import mail
    return mail


def _icon_img(base_url):
    if not base_url:
        return ''
    return (f'<img src="{base_url}/static/icon-192.png" width="40" height="40" '
            f'style="vertical-align:middle;border-radius:10px;margin-right:10px;">')


def _format_date(d: date) -> str:
    """Format a date as e.g. '25th April 2026'."""
    day = d.day
    suffix = ('th' if 11 <= day <= 13
              else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th'))
    return d.strftime(f'{day}{suffix} %B %Y')


def _suspension_date(billing_date: date) -> str:
    """Return the 1st of the month after billing_date, formatted."""
    month = billing_date.month + 1
    year  = billing_date.year
    if month > 12:
        month = 1
        year += 1
    return _format_date(date(year, month, 1))


def send_trial_ending_warning(user, app_url=''):
    """Send the 22nd warning email to a user whose free trial ends on the 25th.

    Returns (ok: bool, detail: str).
    """
    if not user.first_billing_date:
        return False, 'user has no first_billing_date set'
    try:
        from flask_mail import Message
        base_url     = app_url.rstrip('/')
        billing_date = user.first_billing_date
        suspend_date = _suspension_date(billing_date)
        icon         = _icon_img(base_url)

        # Payment link will be a Stripe Checkout URL once Stripe is integrated
        payment_url  = f'{base_url}/billing/add-payment' if base_url else '#'

        html = f"""
<div style="font-family:sans-serif;max-width:520px;">
  <h2 style="color:#0d6efd;">{icon}WindChaser</h2>
  <p>Hi {user.first_name},</p>
  <p>We hope you've been enjoying WindChaser!</p>
  <p>As mentioned when you signed up, WindChaser is a paid service at
     <strong>£3.00/month</strong> — less than a cup of coffee. We promise it will never
     cost more than that, will never include advertising, and your card details are
     handled securely by Stripe, not us.</p>
  <p>Your free trial ends on <strong>{_format_date(billing_date)}</strong>.
     Please add your payment details below — you won't be charged until the 25th.</p>
  <p style="text-align:center;margin:2em 0;">
    <a href="{payment_url}"
       style="background:#0d6efd;color:white;padding:12px 28px;border-radius:6px;
              text-decoration:none;font-weight:bold;font-size:1rem;">
      Add payment details
    </a>
  </p>
  <p style="color:#666;font-size:0.9rem;">
    If you decide WindChaser isn't for you, simply ignore this email and your account
    will be disabled on <strong>{suspend_date}</strong>.
  </p>
</div>"""

        msg = Message(
            subject=f'Your WindChaser free trial ends {_format_date(billing_date)}',
            recipients=[user.email],
            html=html,
        )
        _mail().send(msg)
        return True, 'sent'
    except Exception as e:
        return False, str(e)


def send_renewal_warning(user, app_url=''):
    """Send the 22nd renewal reminder to an existing paying subscriber.

    Returns (ok: bool, detail: str).
    """
    try:
        from flask_mail import Message
        base_url     = app_url.rstrip('/')
        billing_date = user.next_billing_date
        suspend_date = _suspension_date(billing_date)
        icon         = _icon_img(base_url)
        cancel_url   = f'{base_url}/billing/cancel' if base_url else '#'

        html = f"""
<div style="font-family:sans-serif;max-width:520px;">
  <h2 style="color:#0d6efd;">{icon}WindChaser</h2>
  <p>Hi {user.first_name},</p>
  <p>Another month of WindChaser is coming up on <strong>{_format_date(billing_date)}</strong>
     — <strong>£3.00</strong> will be taken from your card on file.</p>
  <p>If for any reason you no longer feel WindChaser is worth the price of a cup of coffee
     a month, we completely understand. Click below and we'll cancel your subscription —
     you'll keep access until <strong>{suspend_date}</strong> and can come back any time.</p>
  <p style="text-align:center;margin:2em 0;">
    <a href="{cancel_url}"
       style="background:#6c757d;color:white;padding:12px 28px;border-radius:6px;
              text-decoration:none;font-weight:bold;font-size:1rem;">
      😊 Cancel my membership
    </a>
  </p>
  <p style="color:#666;font-size:0.9rem;">
    Otherwise, do nothing — we'll take care of everything on the 25th.
  </p>
</div>"""

        msg = Message(
            subject='WindChaser renewal — £3.00 on ' + _format_date(billing_date),
            recipients=[user.email],
            html=html,
        )
        _mail().send(msg)
        return True, 'sent'
    except Exception as e:
        return False, str(e)


def send_payment_failed_email(user, app_url=''):
    """Send the payment failure email after an unsuccessful charge attempt.

    Returns (ok: bool, detail: str).
    """
    try:
        from flask_mail import Message
        base_url     = app_url.rstrip('/')
        billing_date = user.next_billing_date or user.first_billing_date
        suspend_date = _suspension_date(billing_date) if billing_date else 'the 1st'
        icon         = _icon_img(base_url)
        payment_url  = f'{base_url}/billing/add-payment' if base_url else '#'

        html = f"""
<div style="font-family:sans-serif;max-width:520px;">
  <h2 style="color:#dc3545;">{icon}WindChaser — payment problem</h2>
  <p>Hi {user.first_name},</p>
  <p>Unfortunately we were unable to take your <strong>£3.00</strong> payment for WindChaser.
     This can happen for a number of reasons — expired card, insufficient funds, etc.</p>
  <p>Please click below to update your payment details and your account will be
     reinstated immediately.</p>
  <p style="text-align:center;margin:2em 0;">
    <a href="{payment_url}"
       style="background:#dc3545;color:white;padding:12px 28px;border-radius:6px;
              text-decoration:none;font-weight:bold;font-size:1rem;">
      Update payment details
    </a>
  </p>
  <p style="color:#666;font-size:0.9rem;">
    If we don't hear from you by <strong>{suspend_date}</strong>, your account will be
    suspended. You can come back at any time by emailing
    <a href="mailto:windchaser@hamptons.me.uk">windchaser@hamptons.me.uk</a>.
  </p>
</div>"""

        msg = Message(
            subject='WindChaser — payment unsuccessful',
            recipients=[user.email],
            html=html,
        )
        _mail().send(msg)
        return True, 'sent'
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Billing cron — called from admin.py once per cron run
# ---------------------------------------------------------------------------

def run_billing_cron(today: date, app_url: str = '') -> dict | None:
    """Run billing tasks for today. Returns a results dict, or None if nothing to do.

    Guards against running more than once per day by checking the AppLog.
    Only acts on day 22 (warning emails) and day 1 (suspend unpaid users).
    """
    from models import db, User, AppLog
    from billing import get_users_due_warning, get_users_due_suspension
    from log_utils import log_event
    from datetime import datetime

    # Nothing to do on most days
    if today.day not in (1, 22, 25):
        return None

    # Only run once per day — check the log
    today_start = datetime(today.year, today.month, today.day)
    already_run = AppLog.query.filter(
        AppLog.actor == 'CRON',
        AppLog.event_type == 'billing_cron_completed',
        AppLog.timestamp >= today_start,
    ).first()
    if already_run:
        return None

    users = User.query.filter_by(is_active=True).all()
    results = {'warnings_sent': 0, 'warnings_failed': 0,
               'charges_ok': 0, 'charges_failed': 0, 'suspended': 0}

    # Day 22 — send warning emails
    if today.day == 22:
        trial_enders, renewers = get_users_due_warning(users, today)

        for user in trial_enders:
            ok, detail = send_trial_ending_warning(user, app_url)
            if ok:
                log_event('CRON', 'billing_warning_sent',
                          detail=f'{user.email} — trial ending {user.first_billing_date}',
                          user_id=user.id)
                results['warnings_sent'] += 1
            else:
                log_event('CRON', 'billing_warning_failed',
                          detail=f'{user.email} — {detail}', user_id=user.id)
                results['warnings_failed'] += 1

        for user in renewers:
            ok, detail = send_renewal_warning(user, app_url)
            if ok:
                log_event('CRON', 'billing_warning_sent',
                          detail=f'{user.email} — renewal {user.next_billing_date}',
                          user_id=user.id)
                results['warnings_sent'] += 1
            else:
                log_event('CRON', 'billing_warning_failed',
                          detail=f'{user.email} — {detail}', user_id=user.id)
                results['warnings_failed'] += 1

    # Day 25 — charge active/trial users whose billing date is today
    if today.day == 25:
        from billing import get_users_due_payment
        from billing_stripe import charge_customer
        to_charge = get_users_due_payment(users, today)
        for user in to_charge:
            ok, detail = charge_customer(user)
            if ok:
                log_event('CRON', 'billing_charged',
                          detail=f'{user.email} — charged £3.00 (intent {detail})',
                          user_id=user.id)
                results['charges_ok'] += 1
            else:
                log_event('CRON', 'billing_charge_failed',
                          detail=f'{user.email} — {detail}', user_id=user.id)
                results['charges_failed'] += 1
                # _on_payment_failed in billing_stripe handles the webhook-driven path;
                # but if the charge is made directly here (off-session) and fails,
                # we still need to mark the user unpaid and email them.
                user.subscription_status = 'unpaid'
                db.session.commit()
                send_payment_failed_email(user, app_url)

    # Day 1 — suspend unpaid users
    if today.day == 1:
        to_suspend = get_users_due_suspension(users, today)
        for user in to_suspend:
            user.subscription_status = 'cancelled'
            db.session.commit()
            log_event('CRON', 'billing_suspended',
                      detail=f'{user.email}', user_id=user.id)
            results['suspended'] += 1

    log_event('CRON', 'billing_cron_completed',
              detail=(f"Day {today.day}: warnings sent {results['warnings_sent']}, "
                      f"warn failed {results['warnings_failed']}, "
                      f"charges ok {results['charges_ok']}, "
                      f"charges failed {results['charges_failed']}, "
                      f"suspended {results['suspended']}"))
    return results
