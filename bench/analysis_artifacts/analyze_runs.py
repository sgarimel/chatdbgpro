"""Aggregate every run under bench/results/ into a single DataFrame.

For each run we extract:
- run metadata (model, config, case, trial, tier, elapsed_s, status)
- collect.json: tool calls, frequencies, tokens, response, prompt
- case.yaml: criteria text (used to mine ground-truth file/line/function)
- a heuristic correctness signal (file/line/function mention in response)
- whether the harness debugged the *right* binary (BugsCPP cases routinely
  attach gdb to /bin/bash, /bin/sed, /usr/bin/find, etc.)

No judge has been run, so we can't measure root_cause/local_fix/global_fix.
The mention heuristics are upper bounds: a run that does NOT mention the
right file is almost certainly wrong; a run that DOES mention it might
still hallucinate the wrong reasoning. We surface both for inspection.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import yaml
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "bench" / "results"
OUT = ROOT / "bench" / "analysis_artifacts"
OUT.mkdir(parents=True, exist_ok=True)

CMD_RE = re.compile(r"command line:\s*```\s*(.+?)\s*```", re.S)
SYS_BINS = {"/bin/bash", "/usr/bin/bash", "/bin/sh", "/bin/sed", "/usr/bin/find",
            "/usr/bin/make", "/bin/grep", "/usr/bin/grep"}

# Mine ground truth out of free-form criteria text in case.yaml
FILE_RE = re.compile(r"([\w./\-]+\.(?:c|cc|cpp|h|hpp|cxx))", re.I)
LINE_RE = re.compile(r":(\d{1,5})\b")
FUNC_RE = re.compile(r"in function ([A-Za-z_][\w:]*)")

def mine_truth(case_yaml: dict) -> dict:
    crit = case_yaml.get("criteria", {})
    rc = crit.get("root_cause", "") or ""
    lf = crit.get("local_fix", "") or ""
    gf = crit.get("global_fix", "") or ""
    blob = "\n".join([rc, lf, gf])

    # primary file+line: from root_cause sentence "at <file>:<line>"
    file_, line_, func_ = None, None, None
    m = re.search(r"at ([\w./\-]+):(\d+)", rc)
    if m:
        file_, line_ = m.group(1), int(m.group(2))
    m = FUNC_RE.search(rc)
    if m and m.group(1) != "unknown":
        func_ = m.group(1)
    # secondary: pull from synthetic case 'bug:' block
    if not file_:
        bug = case_yaml.get("bug", {})
        rcl = bug.get("root_cause_lines") or []
        if rcl:
            line_ = rcl[0]
        sf = case_yaml.get("source_file")
        if sf: file_ = sf

    # all candidate file basenames mentioned in patch diff
    files = set()
    for f in FILE_RE.findall(blob):
        files.add(Path(f).name)
    if file_:
        files.add(Path(file_).name)

    return {
        "truth_file": file_,
        "truth_file_basename": Path(file_).name if file_ else None,
        "truth_line": line_,
        "truth_function": func_,
        "all_truth_files": sorted(files),
        "bug_category": case_yaml.get("bug", {}).get("category"),
        "bug_error_type": case_yaml.get("bug", {}).get("error_type"),
    }

def score_response(resp: str, truth: dict) -> dict:
    if not resp:
        return {"file_mentioned": False, "line_mentioned": False,
                "func_mentioned": False, "any_truth_file_mentioned": False}
    r = resp
    tf = truth["truth_file_basename"]
    file_hit = bool(tf) and (tf in r)
    line_hit = False
    if truth["truth_line"]:
        # any of [L-3 .. L+3] mentioned as a bare integer is a hit
        L = truth["truth_line"]
        nums_in_resp = set(int(x) for x in re.findall(r"\b(\d{2,5})\b", r))
        line_hit = any((L+d) in nums_in_resp for d in range(-3, 4))
    func_hit = bool(truth["truth_function"]) and (truth["truth_function"] in r)
    any_file = any(f and f in r for f in truth["all_truth_files"])
    return {"file_mentioned": file_hit, "line_mentioned": line_hit,
            "func_mentioned": func_hit, "any_truth_file_mentioned": any_file}

rows = []
for run_dir in sorted(RESULTS.glob("*/*/")):
    if not (run_dir / "result.json").exists():
        continue
    res = json.loads((run_dir / "result.json").read_text())
    suite = run_dir.parent.name

    cy_path = run_dir / "case.yaml"
    case_yaml = {}
    if cy_path.exists():
        try:
            case_yaml = yaml.safe_load(cy_path.read_text()) or {}
        except Exception:
            case_yaml = {}
    truth = mine_truth(case_yaml)

    cj = run_dir / "collect.json"
    cdat = {}
    if cj.exists():
        try:
            cdat = json.loads(cj.read_text())
        except Exception:
            cdat = {}
    queries = cdat.get("queries") or []
    q = queries[0] if queries else {}
    resp = q.get("response", "") or ""
    prompt = q.get("prompt", "") or ""
    stats = q.get("stats") or {}
    tool_freq = q.get("tool_frequency") or {}
    n_tools = q.get("num_tool_calls", 0) or 0

    m = CMD_RE.search(prompt)
    debugged = (m.group(1).strip().split()[0] if m else None)
    valid_target = bool(debugged) and debugged not in SYS_BINS

    score = score_response(resp, truth)

    rows.append({
        "suite": suite,
        "run_id": res.get("run_id"),
        "case_id": res.get("case_id"),
        "model": res.get("model"),
        "tool_config": res.get("tool_config"),
        "context_lines": res.get("context_lines"),
        "trial": res.get("trial"),
        "status": res.get("status"),
        "elapsed_s": res.get("elapsed_s"),
        "language": res.get("language"),
        "debugged_binary": debugged,
        "valid_target": valid_target,
        "is_synthetic": (suite.startswith("full-synthetic") or
                         suite.startswith("smoke") or
                         suite.startswith("step4")),
        "n_tool_calls": n_tools,
        "tool_freq": json.dumps(tool_freq),
        "tokens": stats.get("tokens"),
        "prompt_tokens": stats.get("prompt_tokens"),
        "completion_tokens": stats.get("completion_tokens"),
        "resp_len": len(resp),
        "has_recommendation_section": "Recommendation" in resp,
        "ends_with_questions": resp.rstrip().endswith("?"),
        "bug_category": truth["bug_category"],
        "bug_error_type": truth["bug_error_type"],
        "truth_file": truth["truth_file_basename"],
        "truth_line": truth["truth_line"],
        "truth_function": truth["truth_function"],
        **score,
        "run_dir": str(run_dir),
    })

df = pd.DataFrame(rows)
df.to_csv(OUT / "all_runs.csv", index=False)
print(f"wrote {len(df)} rows to {OUT/'all_runs.csv'}")

# Quick rollups
print("\n=== suite x valid_target ===")
print(df.groupby(["suite", "valid_target"]).size().unstack(fill_value=0))
print("\n=== mention-heuristic by suite (valid runs only) ===")
g = (df[df.valid_target]
     .groupby("suite")
     [["file_mentioned","line_mentioned","func_mentioned","any_truth_file_mentioned"]]
     .mean().round(3))
print(g)
print("\n=== mean tool calls / tokens by model x suite (valid only) ===")
print(df[df.valid_target].groupby(["suite","model"])[["n_tool_calls","tokens","resp_len","elapsed_s"]].mean().round(1))
