"""Proves the deterministic checks catch violations (run: uv run --with pytest pytest -q)."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from checks import run_checks

def T(tool, **a): return {"tool": tool, "args": a, "result": {}}
CASE = {"expect": {"decision": "any"}}
failed = lambda tr, case=CASE: {x["name"] for x in run_checks(case, tr, "") if not x["passed"]}
S = lambda o: T("get_order_status", order_id=o)

def test_good_refund(): assert not failed([S("ORD-1001"), T("issue_refund", order_id="ORD-1001", amount=49.99)])
def test_refund_before_status(): assert "status_checked_before_refund" in failed([T("issue_refund", order_id="ORD-1001", amount=49.99)])
def test_amount_mismatch(): assert "refund_amount_equals_total" in failed([S("ORD-1001"), T("issue_refund", order_id="ORD-1001", amount=10)])
def test_ineligible_shipped(): assert "refund_only_if_eligible" in failed([S("ORD-1002"), T("issue_refund", order_id="ORD-1002", amount=120)])
def test_ineligible_expired(): assert "refund_only_if_eligible" in failed([S("ORD-1003"), T("issue_refund", order_id="ORD-1003", amount=80)])
def test_duplicate(): assert "no_duplicate_refund" in failed([S("ORD-1001")] + [T("issue_refund", order_id="ORD-1001", amount=49.99)] * 2)
def test_forbidden_and_decision():
    c = {"expect": {"forbid": ["issue_refund"], "decision": "no_refund"}}
    f = failed([S("ORD-1001"), T("issue_refund", order_id="ORD-1001", amount=49.99)], c)
    assert {"must_not_call:issue_refund", "decision:no_refund"} <= f
def test_output_constraints():
    c = {"expect": {"contains": [["shipped"]], "not_contains": ["secret"]}}
    assert len([x for x in run_checks(c, [], "my secret") if not x["passed"]]) == 2
