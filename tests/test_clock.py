

def test_period_bounds_inverts_period_of():
    from datetime import date

    from my_planner.clock import period_bounds

    assert period_bounds("day", "2026-10-25") == (date(2026, 10, 25), date(2026, 10, 25))
    assert period_bounds("week", "2026-W43") == (date(2026, 10, 19), date(2026, 10, 25))
    assert period_bounds("week", "2026-W53") == (date(2026, 12, 28), date(2027, 1, 3))
    assert period_bounds("month", "2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert period_bounds("month", "2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    assert period_bounds("quarter", "2026-Q4") == (date(2026, 10, 1), date(2026, 12, 31))
    assert period_bounds("quarter", "2026-Q1") == (date(2026, 1, 1), date(2026, 3, 31))
    assert period_bounds("year", "2026") == (date(2026, 1, 1), date(2026, 12, 31))
