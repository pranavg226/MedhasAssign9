"""Judge vs human agreement. uv run python calibrate.py [--export] [--results results/sample/results.json]
--export writes human_labels_template.json (with replies) for you to label; labels are 0/1/2 per criterion."""
import json, argparse
from judge import CRITERIA

ap = argparse.ArgumentParser(); ap.add_argument("--results", default="results/sample/results.json")
ap.add_argument("--labels", default="human_labels.json"); ap.add_argument("--export", action="store_true"); a = ap.parse_args()
rows = json.load(open(a.results))
if a.export:
    json.dump({r["id"]: {"input": r["input"], "reply": r["response"], **{k: None for k in CRITERIA}} for r in rows},
              open("human_labels_template.json", "w"), indent=1); raise SystemExit("wrote human_labels_template.json")
H = json.load(open(a.labels))


def qwk(x, y, k=3):  # quadratic-weighted Cohen's kappa
    n = len(x); O = [[0] * k for _ in range(k)]
    for i, j in zip(x, y): O[i][j] += 1
    hx = [sum(r) for r in O]; hy = [sum(O[i][j] for i in range(k)) for j in range(k)]
    num = sum((i - j) ** 2 * O[i][j] for i in range(k) for j in range(k))
    den = sum((i - j) ** 2 * hx[i] * hy[j] / n for i in range(k) for j in range(k))
    return 1 - num / den if den else 1.0


L = ["# Judge Calibration", f"{len(rows)} examples x {len(CRITERIA)} criteria, judge vs human (0/1/2).", "",
     "| Criterion | Exact agreement | Within-1 | Weighted kappa |", "|---|---|---|---|"]
dis, allj, allh = [], [], []
for k in CRITERIA:
    j = [r["judge"][k]["score"] for r in rows]; h = [H[r["id"]][k] for r in rows]
    allj += j; allh += h
    L.append(f"| {k} | {sum(a == b for a, b in zip(j, h)) / len(j):.2f} | {sum(abs(a - b) <= 1 for a, b in zip(j, h)) / len(j):.2f} | {qwk(j, h):.2f} |")
    dis += [(r["id"], k, r["judge"][k]["score"], H[r["id"]][k], r["judge"][k]["reason"], r["response"]) for r, a_, b_ in zip(rows, j, h) if a_ != b_]
L.append(f"| **ALL** | {sum(a == b for a, b in zip(allj, allh)) / len(allj):.2f} | {sum(abs(a - b) <= 1 for a, b in zip(allj, allh)) / len(allj):.2f} | {qwk(allj, allh):.2f} |")
L += ["", "## Disagreements (judge != human)", "| Case | Criterion | Judge | Human | Judge reason | Agent reply |", "|---|---|---|---|---|---|"]
L += [f"| {i} | {k} | {a} | {b} | {r} | {t[:80]} |" for i, k, a, b, r, t in dis]
open("calibration.md", "w").write("\n".join(L) + "\n"); print("\n".join(L))
