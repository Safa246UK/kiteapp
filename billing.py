"""
Pure billing logic for WindChaser.

All functions here are side-effect free — no DB writes, no emails, no Stripe calls.
This makes them easy to unit test and reason about independently.

Billing cycle summary:
  - Users get a free trial until their first_billing_date (the first 25th >= 1 month away)
  - 22nd: warning emails sent (3 days before the 25th)
  - 25th: payments processed
  - 1st:  unpaid users suspended

subscription_status values: 'trial' | 'active' | 'unpaid' | 'cancelled'
"""

from datetime import date
import calendar


def calculate_first_billing_date(register_date: date) -> date:
    """Return the first billing date for a user who registers on register_date.

    Rule:
      - If register_date.day <= 25  →  25th of the following month
      - If register_date.day >  25  →  25th of the month after that

    Examples:
      25 Jan → 25 Feb
      26 Jan → 25 Mar
       1 Feb → 25 Mar
      24 Dec → 25 Jan (next year)
      26 Dec → 25 Feb (next year)
    """
    if register_date.day <= 25:
        # Move forward one month
        month = register_date.month + 1
        year  = register_date.year
    else:
        # Move forward two months
        month = register_date.month + 2
        year  = register_date.year

    # Normalise month overflow (e.g. month 13 → Jan next year)
    while month > 12:
        month -= 12
        year  += 1

    return date(year, month, 25)


def is_access_allowed(user, billing_enabled: bool) -> bool:
    """Return True if the user should have full app access.

    When billing_enabled is False every user passes regardless of status —
    this is the kill switch that lets us disable billing in an emergency.
    """
    if not billing_enabled:
        return True
    if user.is_free_for_life:
        return True
    return user.subscription_status in ('trial', 'active')


def get_users_due_warning(users, today: date):
    """Split users into two groups who should receive warning emails on today's date.

    Warning emails go out on the 22nd of each month, 3 days before the 25th.

    Returns:
      trial_enders  — subscription_status='trial',  first_billing_date == today + 3 days
      renewers      — subscription_status='active', next_billing_date  == today + 3 days
    """
    from datetime import timedelta
    target = today + timedelta(days=3)

    trial_enders, renewers = [], []
    for user in users:
        if user.is_free_for_life:
            continue
        if user.subscription_status == 'trial' and user.first_billing_date == target:
            trial_enders.append(user)
        elif user.subscription_status == 'active' and user.next_billing_date == target:
            renewers.append(user)
    return trial_enders, renewers


def get_users_due_payment(users, today: date):
    """Return users whose payment should be attempted today (the 25th).

    Includes trial users whose first_billing_date is today and active users
    whose next_billing_date is today.
    Excludes free-for-life users and users who have requested cancellation
    (they should be suspended on the 1st instead, not charged).
    """
    due = []
    for user in users:
        if user.is_free_for_life:
            continue
        if user.cancellation_requested:
            continue
        if user.subscription_status == 'trial' and user.first_billing_date == today:
            due.append(user)
        elif user.subscription_status == 'active' and user.next_billing_date == today:
            due.append(user)
    return due


def get_users_due_suspension(users, today: date):
    """Return users who should be suspended today (the 1st of the month).

    Two groups:
      - subscription_status='unpaid'  (payment failed or no card on file)
      - cancellation_requested=True   (user cancelled, grace period has expired)
    """
    due = []
    for user in users:
        if user.is_free_for_life:
            continue
        if user.subscription_status == 'unpaid':
            due.append(user)
        elif user.cancellation_requested and user.subscription_status in ('trial', 'active'):
            due.append(user)
    return due


def advance_billing_date(current_date: date) -> date:
    """Advance a billing date by one month, always landing on the 25th."""
    month = current_date.month + 1
    year  = current_date.year
    if month > 12:
        month = 1
        year += 1
    return date(year, month, 25)
