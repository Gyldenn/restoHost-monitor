# Testear get_kpi_status y priority_badge directamente
def test_get_kpi_status_critical_higher_is_worse():
    from dashboard.components import get_kpi_status
    assert get_kpi_status(0.30, 0.15, 0.25, "higher_is_worse") == "critical"

def test_get_kpi_status_warning():
    from dashboard.components import get_kpi_status
    assert get_kpi_status(0.18, 0.15, 0.25, "higher_is_worse") == "warning"

def test_get_kpi_status_ok():
    from dashboard.components import get_kpi_status
    assert get_kpi_status(0.10, 0.15, 0.25, "higher_is_worse") == "ok"

def test_get_kpi_status_no_data():
    from dashboard.components import get_kpi_status
    assert get_kpi_status(None, 0.15, 0.25, "higher_is_worse") == "no_data"

def test_priority_badge_high():
    from dashboard.components import priority_badge
    from shared.enums import Priority
    assert priority_badge(Priority.HIGH) == "🔴"

def test_priority_badge_none():
    from dashboard.components import priority_badge
    assert priority_badge(None) == "⚪"
