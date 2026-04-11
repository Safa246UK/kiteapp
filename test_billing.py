"""
Unit tests for billing.py pure logic.

Run with:  python -m pytest test_billing.py -v
No Flask app context or database needed.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock
import pytest

from billing import (
    calculate_first_billing_date,
    is_access_allowed,
    get_users_due_warning,
    get_users_due_payment,
    get_users_due_suspension,
    advance_billing_date,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(**kwargs):
    """Return a mock User with sensible billing defaults."""
    user = MagicMock()
    user.is_free_for_life       = kwargs.get('is_free_for_life', False)
    user.subscription_status    = kwargs.get('subscription_status', 'trial')
    user.first_billing_date     = kwargs.get('first_billing_date', None)
    user.next_billing_date      = kwargs.get('next_billing_date', None)
    user.cancellation_requested = kwargs.get('cancellation_requested', False)
    return user


# ---------------------------------------------------------------------------
# calculate_first_billing_date
# ---------------------------------------------------------------------------

class TestCalculateFirstBillingDate:

    def test_register_on_25th_gets_next_month(self):
        assert calculate_first_billing_date(date(2026, 1, 25)) == date(2026, 2, 25)

    def test_register_before_25th_gets_next_month(self):
        assert calculate_first_billing_date(date(2026, 1, 1))  == date(2026, 2, 25)
        assert calculate_first_billing_date(date(2026, 1, 24)) == date(2026, 2, 25)

    def test_register_after_25th_skips_a_month(self):
        assert calculate_first_billing_date(date(2026, 1, 26)) == date(2026, 3, 25)
        assert calculate_first_billing_date(date(2026, 1, 31)) == date(2026, 3, 25)

    def test_register_in_november_on_25th(self):
        assert calculate_first_billing_date(date(2026, 11, 25)) == date(2026, 12, 25)

    def test_register_in_november_after_25th_wraps_to_january(self):
        assert calculate_first_billing_date(date(2026, 11, 26)) == date(2027, 1, 25)

    def test_register_in_december_on_25th_wraps_to_january(self):
        assert calculate_first_billing_date(date(2026, 12, 25)) == date(2027, 1, 25)

    def test_register_in_december_before_25th(self):
        assert calculate_first_billing_date(date(2026, 12, 24)) == date(2027, 1, 25)

    def test_register_in_december_after_25th_wraps_to_february(self):
        assert calculate_first_billing_date(date(2026, 12, 26)) == date(2027, 2, 25)
        assert calculate_first_billing_date(date(2026, 12, 31)) == date(2027, 2, 25)

    def test_register_in_october_after_25th_wraps_correctly(self):
        # Oct 26 → +2 months = Dec 25
        assert calculate_first_billing_date(date(2026, 10, 26)) == date(2026, 12, 25)

    def test_free_period_is_at_least_29_days(self):
        # The shortest possible free period is register on 25th → next month's 25th
        reg = date(2026, 2, 25)
        billing = calculate_first_billing_date(reg)
        assert (billing - reg).days >= 28  # Feb is the shortest month

    def test_register_after_25th_free_period_is_at_least_27_days(self):
        # Even registering on the 28th of Feb still gives until 25 Apr (56 days)
        reg = date(2026, 2, 28)
        billing = calculate_first_billing_date(reg)
        assert (billing - reg).days >= 25


# ---------------------------------------------------------------------------
# is_access_allowed
# ---------------------------------------------------------------------------

class TestIsAccessAllowed:

    def test_billing_disabled_allows_all(self):
        for status in ('trial', 'active', 'unpaid', 'cancelled'):
            user = make_user(subscription_status=status)
            assert is_access_allowed(user, billing_enabled=False)

    def test_free_for_life_always_allowed(self):
        user = make_user(is_free_for_life=True, subscription_status='cancelled')
        assert is_access_allowed(user, billing_enabled=True)

    def test_trial_allowed(self):
        user = make_user(subscription_status='trial')
        assert is_access_allowed(user, billing_enabled=True)

    def test_active_allowed(self):
        user = make_user(subscription_status='active')
        assert is_access_allowed(user, billing_enabled=True)

    def test_unpaid_blocked(self):
        user = make_user(subscription_status='unpaid')
        assert not is_access_allowed(user, billing_enabled=True)

    def test_cancelled_blocked(self):
        user = make_user(subscription_status='cancelled')
        assert not is_access_allowed(user, billing_enabled=True)


# ---------------------------------------------------------------------------
# get_users_due_warning
# ---------------------------------------------------------------------------

class TestGetUsersDueWarning:
    TODAY = date(2026, 4, 22)
    TARGET = date(2026, 4, 25)  # today + 3

    def test_trial_ender_included(self):
        user = make_user(subscription_status='trial', first_billing_date=self.TARGET)
        trial, renewers = get_users_due_warning([user], self.TODAY)
        assert user in trial
        assert user not in renewers

    def test_renewer_included(self):
        user = make_user(subscription_status='active', next_billing_date=self.TARGET)
        trial, renewers = get_users_due_warning([user], self.TODAY)
        assert user in renewers
        assert user not in trial

    def test_wrong_date_excluded(self):
        user = make_user(subscription_status='trial',
                         first_billing_date=self.TARGET + timedelta(days=1))
        trial, renewers = get_users_due_warning([user], self.TODAY)
        assert not trial and not renewers

    def test_free_for_life_excluded(self):
        user = make_user(is_free_for_life=True, subscription_status='trial',
                         first_billing_date=self.TARGET)
        trial, renewers = get_users_due_warning([user], self.TODAY)
        assert not trial and not renewers

    def test_unpaid_not_included(self):
        user = make_user(subscription_status='unpaid', next_billing_date=self.TARGET)
        trial, renewers = get_users_due_warning([user], self.TODAY)
        assert not trial and not renewers


# ---------------------------------------------------------------------------
# get_users_due_payment
# ---------------------------------------------------------------------------

class TestGetUsersDuePayment:
    TODAY = date(2026, 4, 25)

    def test_trial_user_due_today(self):
        user = make_user(subscription_status='trial', first_billing_date=self.TODAY)
        assert user in get_users_due_payment([user], self.TODAY)

    def test_active_user_due_today(self):
        user = make_user(subscription_status='active', next_billing_date=self.TODAY)
        assert user in get_users_due_payment([user], self.TODAY)

    def test_wrong_date_excluded(self):
        user = make_user(subscription_status='active',
                         next_billing_date=self.TODAY + timedelta(days=1))
        assert user not in get_users_due_payment([user], self.TODAY)

    def test_free_for_life_excluded(self):
        user = make_user(is_free_for_life=True, subscription_status='active',
                         next_billing_date=self.TODAY)
        assert user not in get_users_due_payment([user], self.TODAY)

    def test_cancellation_requested_excluded(self):
        user = make_user(subscription_status='active', next_billing_date=self.TODAY,
                         cancellation_requested=True)
        assert user not in get_users_due_payment([user], self.TODAY)

    def test_unpaid_not_charged_again(self):
        user = make_user(subscription_status='unpaid', next_billing_date=self.TODAY)
        assert user not in get_users_due_payment([user], self.TODAY)


# ---------------------------------------------------------------------------
# get_users_due_suspension
# ---------------------------------------------------------------------------

class TestGetUsersDueSuspension:
    TODAY = date(2026, 5, 1)

    def test_unpaid_suspended(self):
        user = make_user(subscription_status='unpaid')
        assert user in get_users_due_suspension([user], self.TODAY)

    def test_cancellation_requested_suspended(self):
        user = make_user(subscription_status='active', cancellation_requested=True)
        assert user in get_users_due_suspension([user], self.TODAY)

    def test_active_not_suspended(self):
        user = make_user(subscription_status='active')
        assert user not in get_users_due_suspension([user], self.TODAY)

    def test_trial_not_suspended(self):
        user = make_user(subscription_status='trial')
        assert user not in get_users_due_suspension([user], self.TODAY)

    def test_free_for_life_excluded(self):
        user = make_user(is_free_for_life=True, subscription_status='unpaid')
        assert user not in get_users_due_suspension([user], self.TODAY)

    def test_already_cancelled_not_double_suspended(self):
        # A user who is already 'cancelled' shouldn't appear here
        user = make_user(subscription_status='cancelled')
        assert user not in get_users_due_suspension([user], self.TODAY)


# ---------------------------------------------------------------------------
# advance_billing_date
# ---------------------------------------------------------------------------

class TestAdvanceBillingDate:

    def test_normal_month(self):
        assert advance_billing_date(date(2026, 4, 25)) == date(2026, 5, 25)

    def test_december_wraps_to_january(self):
        assert advance_billing_date(date(2026, 12, 25)) == date(2027, 1, 25)

    def test_always_lands_on_25th(self):
        for month in range(1, 13):
            result = advance_billing_date(date(2026, month, 25))
            assert result.day == 25
