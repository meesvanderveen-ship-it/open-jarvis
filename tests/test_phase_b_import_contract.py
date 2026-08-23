from bot.execution_planner import ExecutionPlanner, ReadOnlyExecutionPlanner
from bot.order_plan import OrderPlan, PaperOrderPlan, build_order_intent_from_execution_plan, is_actionable_order_intent
from bot.limit_order_manager import PaperLimitOrderManager
from bot.order_store import OrderStore


def test_execution_planner_alias_is_backward_compatible():
    assert ExecutionPlanner is ReadOnlyExecutionPlanner


def test_order_plan_wrapper_is_dict_compatible():
    plan = OrderPlan.from_dict({"ticker": "BTC-USDC", "status": "planned"})
    assert isinstance(plan, dict)
    assert plan.to_dict()["ticker"] == "BTC-USDC"
    paper = PaperOrderPlan.from_dict({"paper_only": True})
    assert paper["paper_only"] is True


def test_phase_b_core_imports_exist():
    assert callable(build_order_intent_from_execution_plan)
    assert callable(is_actionable_order_intent)
    assert PaperLimitOrderManager.__name__ == "PaperLimitOrderManager"
    assert OrderStore.__name__ == "OrderStore"
