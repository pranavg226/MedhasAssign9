"""Run the full pipeline: agent -> deterministic checks -> judge -> report. Exit code 1 if the release gate fails.
uv run python run_eval.py --mode mock|mock-buggy|live [--regression-only] [--out results/x]"""
import argparse, json, os, collections
from tools import Env
from agent import run_agent
from checks import run_checks
from judge import judge, CRITERIA

GATE = {"pass_rate": 0.85, "regression_pass_rate": 1.0}
RECS = {
 "decision": "Decision errors: add explicit few-shot examples of refusing/clarifying, and a pre-refund policy checklist in the system prompt.",
 "policy": "Policy violations (amount/eligibility): add a server-side guard in issue_refund (reject amount != total or ineligible order) - do not rely on the prompt alone.",
 "sequence": "Sequencing: enforce get_order_status-before-issue_refund in the tool layer (refund requires a prior status token).",
 "params": "Tool params: handle multi-order messages (loop over all ids) and normalise order ids / non-English requests.",
 "tool_selection": "Tool selection: add routing examples for policy questions, missing ids and off-topic requests.",
 "output": "Output constraints: add response templates that always state outcome, order id and amount.",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="mock", choices=["mock", "mock-buggy", "live"])
    ap.add_argument("--regression-only", action="store_true")
    ap.add_argument("--out", default="results/latest")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cases = [c for c in json.load(open("dataset.json")) if c["regression"] or not a.regression_only]
    rows = []
    for c in cases:
        env = Env()
        try: traj, resp = run_agent(c["input"], env, a.mode)
        except Exception as ex: traj, resp = [], f"AGENT_ERROR: {ex}"; print(c["id"], resp)
        checks = run_checks(c, traj, resp)
        j = None if a.regression_only else judge(c, traj, resp, a.mode)
        det_ok = all(x["passed"] for x in checks)
        judge_ok = j is None or min(j[k]["score"] for k in CRITERIA) >= 1
        rows.append({"id": c["id"], "category": c["category"], "regression": c["regression"], "input": c["input"],
                     "trajectory": traj, "response": resp, "checks": checks, "judge": j,
                     "det_pass": det_ok, "judge_pass": judge_ok, "pass": det_ok and judge_ok})
    json.dump(rows, open(f"{a.out}/results.json", "w"), indent=1)
    m = metrics(rows)
    reg = [r for r in rows if r["regression"]]
    json.dump({"mode": a.mode, "regression": [{"id": r["id"], "input": r["input"], "pass": r["det_pass"],
               "failed": [x["name"] for x in r["checks"] if not x["passed"]]} for r in reg]}, open(f"{a.out}/regression.json", "w"), indent=1)
    gate = m["pass_rate"] >= GATE["pass_rate"] and m["regression_pass_rate"] >= GATE["regression_pass_rate"]
    if not a.regression_only:
        open(f"{a.out}/report.md", "w").write(report(rows, m, a.mode, gate))
    print(json.dumps({**m, "gate": "PASS" if gate else "FAIL", "mode": a.mode}, indent=1))
    raise SystemExit(0 if gate else 1)


FIX = {"refund_only_if_eligible": "Agent refunded an ineligible order: add eligibility guard in issue_refund + prompt rule.",
       "refund_amount_equals_total": "Refund amount != order total: force amount from get_order_status result, never from user text.",
       "status_checked_before_refund": "Refund without status lookup: require status call in tool layer.",
       "no_duplicate_refund": "Duplicate refund attempt: make issue_refund idempotent per order.",
       "must_not_refund": "Refunded an order the user never legitimately asked for (injection/confusion): only act on the user's own explicit request.",
       "decision": "Wrong refund/no-refund decision for this request type.",
       "status_lookup_param": "Missed an order id (multi-order / non-English / casing): iterate over all ids.",
       "contains_any": "Reply omitted required facts (status, amount or reason).", "not_contains": "Reply leaked or produced forbidden content."}


def rate(xs): return round(sum(xs) / len(xs), 3) if xs else None


def metrics(rows):
    grp = lambda g: rate([all(x["passed"] for x in r["checks"] if x["group"] in g) for r in rows if any(x["group"] in g for x in r["checks"])])
    reg = [r for r in rows if r["regression"]]
    m = {"n": len(rows), "pass_rate": rate([r["pass"] for r in rows]), "deterministic_pass_rate": rate([r["det_pass"] for r in rows]),
         "task_completion": grp({"decision"}), "output_accuracy": grp({"output"}),
         "trajectory_pass_rate": grp({"tool_selection", "params", "sequence", "policy"}),
         "regression_pass_rate": rate([r["det_pass"] for r in reg]),
         "by_category": {k: rate([r["pass"] for r in rows if r["category"] == k]) for k in sorted({r["category"] for r in rows})}}
    if rows[0]["judge"]:
        m["judge_mean_per_criterion(0-2)"] = {k: round(sum(r["judge"][k]["score"] for r in rows) / len(rows), 2) for k in CRITERIA}
        m["response_quality(0-1)"] = round(sum(r["judge"][k]["score"] for r in rows for k in CRITERIA) / (2 * len(CRITERIA) * len(rows)), 3)
    return m


def report(rows, m, mode, gate):
    L = [f"# Agent Evaluation Report (mode: `{mode}`)", "",
         f"**Release gate: {'PASS' if gate else 'FAIL'}** (overall pass >= {GATE['pass_rate']}, regression pass = {GATE['regression_pass_rate']})", ""]
    if mode.startswith("mock"):
        L += ["> Mock agent + heuristic judge: demonstrates the pipeline offline. Re-run with `--mode live` for real agent numbers.", ""]
    L += ["## 1. Overall scores", "| Metric | Value |", "|---|---|"]
    for k, v in m.items():
        if k != "by_category": L.append(f"| {k} | {v} |")
    L += ["", "| Category | Pass rate |", "|---|---|"] + [f"| {k} | {v} |" for k, v in m["by_category"].items()]
    L += ["", "## 2. Failure analysis"]
    groups = collections.Counter()
    for r in rows:
        if r["pass"]: continue
        bad = [x for x in r["checks"] if not x["passed"]]
        groups.update({x["group"] for x in bad})
        L.append(f"- **{r['id']}** ({r['category']}) `{r['input']}`")
        for x in bad:
            fx = next((v for k, v in FIX.items() if x["name"].startswith(k)), "")
            L.append(f"  - deterministic FAIL `{x['name']}` [{x['group']}] {x['detail']} -> **Fix:** {fx}")
        if r["judge"]:
            for k in CRITERIA:
                if r["judge"][k]["score"] < 2: L.append(f"  - judge `{k}`={r['judge'][k]['score']}: {r['judge'][k]['reason']}")
        L.append(f"  - reply: _{r['response']}_")
    L += ["", "## 3. Regression results", "| Case | Result | Failed checks |", "|---|---|---|"]
    for r in rows:
        if r["regression"]:
            L.append(f"| {r['id']} {r['input'][:55]} | {'PASS' if r['det_pass'] else 'FAIL'} | {', '.join(x['name'] for x in r['checks'] if not x['passed']) or '-'} |")
    L += ["", "## 4. Recommendations"] + [f"- {RECS[g]}" for g, _ in groups.most_common()]
    if not groups: L.append("- No deterministic failures; expand the dataset with new production failures.")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
