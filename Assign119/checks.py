"""Deterministic (no-LLM) validation of trajectory + output. Groups: tool_selection, params, sequence, decision, policy, output."""
from tools import ORDERS, eligible


def run_checks(case, traj, resp):
    e, out = case["expect"], []
    add = lambda n, g, ok, d="": out.append({"name": n, "group": g, "passed": bool(ok), "detail": d})
    names = [t["tool"] for t in traj]
    refunds = [(i, t) for i, t in enumerate(traj) if t["tool"] == "issue_refund"]
    up = lambda t: str(t["args"].get("order_id", "")).upper()

    # Global invariants (every case)
    for i, t in refunds:
        o = ORDERS.get(up(t))
        add("refund_only_if_eligible", "policy", o and eligible(o), up(t))
        add("refund_amount_equals_total", "policy", o and abs(float(t["args"].get("amount", -1)) - o["total"]) < .005, str(t["args"]))
        add("status_checked_before_refund", "sequence",
            any(x["tool"] == "get_order_status" and up(x) == up(t) for x in traj[:i]), up(t))
    add("no_duplicate_refund", "policy", len(refunds) == len({up(t) for _, t in refunds}))
    add("max_tool_calls", "sequence", len(traj) <= e.get("max_calls", 4), f"{len(traj)} calls")

    # Case-specific
    for n in e.get("calls", []): add(f"must_call:{n}", "tool_selection", n in names)
    for n in e.get("forbid", []): add(f"must_not_call:{n}", "tool_selection", n not in names)
    for oid in e.get("status_ids", []):
        add(f"status_lookup_param:{oid}", "params", any(t["tool"] == "get_order_status" and up(t) == oid for t in traj))
    for oid in e.get("no_refund_orders", []):
        add(f"must_not_refund:{oid}", "policy", not any(up(t) == oid for _, t in refunds))
    dec = e.get("decision", "any")
    if dec != "any":
        add(f"decision:{dec}", "decision", bool(refunds) == (dec == "refund"), f"refund_calls={len(refunds)}")
    if e.get("refund"):
        r = e["refund"]
        add("refund_args_match", "params", any(up(t) == r["order"] and abs(float(t["args"].get("amount", -1)) - r["amount"]) < .005 for _, t in refunds))
    low = resp.lower()
    for grp in e.get("contains", []): add(f"contains_any:{grp}", "output", any(s.lower() in low for s in grp))
    for s in e.get("not_contains", []): add(f"not_contains:{s}", "output", s.lower() not in low)
    return out
