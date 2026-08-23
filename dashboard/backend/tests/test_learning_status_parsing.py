from dashboard.backend.services.learning_status import get_learning_status
from dashboard.backend.services.shell_tool import ToolExecutionError


def test_learning_status_runs_against_real_tool_or_raises_cleanly():
    try:
        result = get_learning_status()
    except ToolExecutionError:
        return
    assert isinstance(result, dict)
    assert "product_readiness" in result
