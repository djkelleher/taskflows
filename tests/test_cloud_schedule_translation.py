"""Tests for cloud schedule translation utilities.

This test module validates that taskflows schedules (Calendar and Periodic)
are correctly translated to cloud-native schedule expressions like
AWS EventBridge cron() and rate() expressions.
"""

import pytest

from taskflows.schedule import Calendar, Periodic
from taskflows.cloud.utils import (
    schedule_to_eventbridge_expression,
    _calendar_to_cron,
    _periodic_to_rate,
)


class TestCalendarToCron:
    """Test Calendar schedule to EventBridge cron expression conversion."""

    def test_weekday_schedule(self):
        """Test Mon-Fri schedule conversion."""
        schedule = Calendar(schedule="Mon-Fri 14:00")
        result = _calendar_to_cron(schedule)
        assert result == "cron(00 14 ? * MON-FRI *)"

    def test_specific_days(self):
        """Test specific days (Mon,Wed,Fri) schedule."""
        schedule = Calendar(schedule="Mon,Wed,Fri 09:30")
        result = _calendar_to_cron(schedule)
        assert result == "cron(30 09 ? * MON,WED,FRI *)"

    def test_single_day(self):
        """Test single day schedule."""
        schedule = Calendar(schedule="Sun 17:00")
        result = _calendar_to_cron(schedule)
        assert result == "cron(00 17 ? * SUN *)"

    def test_daily_schedule(self):
        """Test daily (all days) schedule."""
        schedule = Calendar(schedule="Mon-Sun 00:00")
        result = _calendar_to_cron(schedule)
        assert result == "cron(00 00 ? * * *)"

    def test_with_seconds(self):
        """Test schedule with seconds (should ignore seconds)."""
        schedule = Calendar(schedule="Mon-Fri 16:30:45")
        result = _calendar_to_cron(schedule)
        # EventBridge doesn't support seconds, should use just hours:minutes
        assert result == "cron(30 16 ? * MON-FRI *)"

    def test_midnight(self):
        """Test midnight schedule."""
        schedule = Calendar(schedule="Mon-Fri 00:00")
        result = _calendar_to_cron(schedule)
        assert result == "cron(00 00 ? * MON-FRI *)"


class TestPeriodicToRate:
    """Test Periodic schedule to EventBridge rate expression conversion."""

    def test_hourly_rate(self):
        """Test hourly schedule."""
        schedule = Periodic(start_on="boot", period=3600, relative_to="finish")
        result = _periodic_to_rate(schedule)
        assert result == "rate(1 hour)"

    def test_multi_hour_rate(self):
        """Test multiple hours schedule."""
        schedule = Periodic(start_on="command", period=7200, relative_to="start")
        result = _periodic_to_rate(schedule)
        assert result == "rate(2 hours)"

    def test_daily_rate(self):
        """Test daily schedule."""
        schedule = Periodic(start_on="boot", period=86400, relative_to="finish")
        result = _periodic_to_rate(schedule)
        assert result == "rate(1 day)"

    def test_multi_day_rate(self):
        """Test multiple days schedule."""
        schedule = Periodic(start_on="login", period=172800, relative_to="start")
        result = _periodic_to_rate(schedule)
        assert result == "rate(2 days)"

    def test_minutes_rate(self):
        """Test minutes schedule."""
        schedule = Periodic(start_on="boot", period=300, relative_to="finish")
        result = _periodic_to_rate(schedule)
        assert result == "rate(5 minutes)"

    def test_single_minute_rate(self):
        """Test 1-minute schedule (singular form)."""
        schedule = Periodic(start_on="boot", period=60, relative_to="finish")
        result = _periodic_to_rate(schedule)
        assert result == "rate(1 minute)"

    def test_sub_minute_raises_error(self):
        """Test that sub-minute schedules raise an error."""
        schedule = Periodic(start_on="boot", period=30, relative_to="finish")
        with pytest.raises(ValueError, match="at least 1 minute"):
            _periodic_to_rate(schedule)


class TestScheduleToEventBridge:
    """Test the main schedule_to_eventbridge_expression function."""

    def test_calendar_schedule(self):
        """Test Calendar schedule conversion."""
        schedule = Calendar(schedule="Mon-Fri 10:00")
        result = schedule_to_eventbridge_expression(schedule)
        assert result == "cron(00 10 ? * MON-FRI *)"

    def test_periodic_schedule(self):
        """Test Periodic schedule conversion."""
        schedule = Periodic(start_on="boot", period=3600, relative_to="finish")
        result = schedule_to_eventbridge_expression(schedule)
        assert result == "rate(1 hour)"

    def test_unknown_schedule_type_raises_error(self):
        """Test that unknown schedule types raise an error."""
        # Create a mock schedule object that isn't Calendar or Periodic
        class UnknownSchedule:
            pass

        with pytest.raises(ValueError, match="Unknown schedule type"):
            schedule_to_eventbridge_expression(UnknownSchedule())


class TestRealWorldScenarios:
    """Test real-world schedule scenarios."""

    def test_daily_backup(self):
        """Test typical daily backup schedule."""
        schedule = Calendar(schedule="Mon-Sun 02:00")
        result = schedule_to_eventbridge_expression(schedule)
        assert result == "cron(00 02 ? * * *)"

    def test_business_hours_monitoring(self):
        """Test business hours monitoring (every 15 minutes during weekdays)."""
        schedule = Periodic(start_on="boot", period=900, relative_to="finish")
        result = schedule_to_eventbridge_expression(schedule)
        assert result == "rate(15 minutes)"

    def test_weekend_cleanup(self):
        """Test weekend cleanup schedule."""
        # Note: For weekends, you'd need two separate Calendar schedules
        # or use a pattern like Sat,Sun
        saturday = Calendar(schedule="Sat 00:00")
        sunday = Calendar(schedule="Sun 00:00")

        sat_result = schedule_to_eventbridge_expression(saturday)
        sun_result = schedule_to_eventbridge_expression(sunday)

        assert sat_result == "cron(00 00 ? * SAT *)"
        assert sun_result == "cron(00 00 ? * SUN *)"

    def test_quarterly_report(self):
        """Test quarterly schedule (every 90 days)."""
        schedule = Periodic(start_on="boot", period=90 * 86400, relative_to="finish")
        result = schedule_to_eventbridge_expression(schedule)
        assert result == "rate(90 days)"


# Fixtures for common test data
@pytest.fixture
def common_schedules():
    """Provide common schedule configurations."""
    return {
        "hourly": Periodic(start_on="boot", period=3600, relative_to="finish"),
        "daily": Calendar(schedule="Mon-Sun 00:00"),
        "weekdays": Calendar(schedule="Mon-Fri 09:00"),
        "weekends": Calendar(schedule="Sat,Sun 10:00"),
    }


def test_common_schedules(common_schedules):
    """Test common schedule patterns."""
    assert schedule_to_eventbridge_expression(common_schedules["hourly"]) == "rate(1 hour)"
    assert schedule_to_eventbridge_expression(common_schedules["daily"]) == "cron(00 00 ? * * *)"
    assert (
        schedule_to_eventbridge_expression(common_schedules["weekdays"])
        == "cron(00 09 ? * MON-FRI *)"
    )
    assert (
        schedule_to_eventbridge_expression(common_schedules["weekends"])
        == "cron(00 10 ? * SAT,SUN *)"
    )


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
