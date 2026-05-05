"""GDB-call distribution by model on the 11 external-native cases.

Reads collect.json from each run dir of a results suite, aggregates
tool_frequency keyed by GDB command, normalizes aliases, and writes:
  - <suite>/analysis/gdb_call_distribution_counts.png      (stacked bar, raw counts)
  - <suite>/analysis/gdb_call_distribution_fraction.png    (stacked bar, fractions)
  - <suite>/analysis/gdb_call_distribution_heatmap.png     (heatmap, model x cmd)
  - <suite>/analysis/gdb_call_distribution.csv             (long-form table)
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ALIAS = {
    "bt": "backtrace",
    "where": "backtrace",
    "p": "print",
    "p/x": "print",
    "print/x": "print",
    "b": "break",
    "c": "continue",
    "s": "step",
    "n": "next",
    "r": "run",
}

# Anything starting with x/ collapses to "x"
def normalize(cmd: str) -> str | None:
    cmd = cmd.strip()
    if not cmd:
        return None
    if cmd.startswith("#"):  # comment lines
        return None
    if cmd in {"code", "shell", "grep", "search", "llm_debug", "find_definition", "check_my_work"}:
        # Not a gdb command per se
        return None
    if cmd.startswith("x/") or cmd == "x":
        return "x"
    if cmd.startswith("strlen("):  # gdb 'call' style — too case-specific
        return "call"
    cmd = ALIAS.get(cmd, cmd)
    # Skip anything that looks like a fragment / alias junk
    return cmd


def short_model(model: str) -> str:
    m = model.lower()
    if "sonnet" in m: return "sonnet-4.5"
    if "gpt-5" in m: return "gpt-5.5"
    if "gemini" in m: return "gemini-3.1-FL"
    if "qwen" in m: return "qwen-30B"
    if "nemotron" in m: return "nemotron-30B"
    return model


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suite", help="Path to merged suite, e.g. bench/results/<name>")
    p.add_argument("--top", type=int, default=10,
                   help="Show top-N commands across all models, group rest as 'other'.")
    p.add_argument("--tier", type=int, default=3,
                   help="Only include runs from this tier (default: 3 — pure gdb tool).")
    args = p.parse_args()

    suite = Path(args.suite).resolve()
    out_dir = suite / "analysis"
    out_dir.mkdir(exist_ok=True)

    # Aggregate: per_model[model][cmd] = count
    per_model: dict[str, Counter] = defaultdict(Counter)
    per_model_runs: Counter = Counter()  # how many runs per model (for run-normalized fractions later if wanted)

    for d in sorted(suite.iterdir()):
        if not d.is_dir():
            continue
        if f"__tier{args.tier}__" not in d.name:
            continue
        cj = d / "collect.json"
        rj = d / "result.json"
        if not (cj.exists() and rj.exists()):
            continue
        try:
            res = json.loads(rj.read_text())
            coll = json.loads(cj.read_text())
        except Exception:
            continue
        model = short_model(res.get("model", "?"))
        per_model_runs[model] += 1
        queries = coll.get("queries") or []
        if not queries:
            continue
        tf = queries[0].get("tool_frequency") or {}
        for cmd, n in tf.items():
            ncmd = normalize(cmd)
            if ncmd is None:
                continue
            per_model[model][ncmd] += int(n)

    if not per_model:
        print("no data found")
        return 1

    # Determine top-N commands across models
    grand = Counter()
    for cnt in per_model.values():
        grand.update(cnt)
    top_cmds = [c for c, _ in grand.most_common(args.top)]
    other_cmds = [c for c in grand if c not in top_cmds]

    # Build matrix [models x (top_cmds + other)]
    models = sorted(per_model.keys())
    cols = top_cmds + (["other"] if other_cmds else [])
    M = np.zeros((len(models), len(cols)), dtype=int)
    for i, m in enumerate(models):
        for j, c in enumerate(top_cmds):
            M[i, j] = per_model[m].get(c, 0)
        if other_cmds:
            M[i, -1] = sum(per_model[m].get(c, 0) for c in other_cmds)

    # CSV (long form)
    csv_path = out_dir / "gdb_call_distribution.csv"
    with csv_path.open("w") as f:
        f.write("model,command,count\n")
        for m in models:
            for c in cols:
                f.write(f"{m},{c},{per_model[m].get(c, 0) if c != 'other' else sum(per_model[m].get(x, 0) for x in other_cmds)}\n")

    # 1) stacked bar — counts
    fig, ax = plt.subplots(figsize=(11, 6))
    bottom = np.zeros(len(models))
    cmap = plt.cm.tab20.colors + plt.cm.Set3.colors
    for j, c in enumerate(cols):
        ax.bar(models, M[:, j], bottom=bottom, label=c, color=cmap[j % len(cmap)])
        bottom += M[:, j]
    ax.set_ylabel(f"Total GDB-command invocations across 11 external-native cases (Tier {args.tier})")
    ax.set_title(f"GDB-call distribution by model (Tier {args.tier})")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=9)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    out1 = out_dir / "gdb_call_distribution_counts.png"
    fig.savefig(out1, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 2) stacked bar — fraction within each model
    F = M.astype(float)
    row_sums = F.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    F = F / row_sums
    fig, ax = plt.subplots(figsize=(11, 6))
    bottom = np.zeros(len(models))
    for j, c in enumerate(cols):
        ax.bar(models, F[:, j], bottom=bottom, label=c, color=cmap[j % len(cmap)])
        bottom += F[:, j]
    ax.set_ylabel("Fraction of GDB calls (per model)")
    ax.set_title(f"GDB-call composition by model — Tier {args.tier} (fractions sum to 1)")
    ax.set_ylim(0, 1)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), fontsize=9)
    plt.xticks(rotation=20, ha="right")
    plt.tight_layout()
    out2 = out_dir / "gdb_call_distribution_fraction.png"
    fig.savefig(out2, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # 3) heatmap (counts)
    fig, ax = plt.subplots(figsize=(11, 5))
    im = ax.imshow(M, aspect="auto", cmap="YlGnBu")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols, rotation=30, ha="right")
    ax.set_yticks(range(len(models)))
    ax.set_yticklabels(models)
    for i in range(len(models)):
        for j in range(len(cols)):
            v = M[i, j]
            if v:
                ax.text(j, i, str(v), ha="center", va="center",
                        fontsize=9,
                        color="white" if v > M.max() / 2 else "black")
    ax.set_title(f"GDB-call counts: model × command (Tier {args.tier})")
    fig.colorbar(im, ax=ax, label="invocations")
    plt.tight_layout()
    out3 = out_dir / "gdb_call_distribution_heatmap.png"
    fig.savefig(out3, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"models={models}")
    print(f"top_commands={top_cmds}")
    if other_cmds:
        print(f"other ({len(other_cmds)}): {sorted(other_cmds)}")
    print("totals per model:")
    for m, total in zip(models, M.sum(axis=1)):
        print(f"  {m}: {total}")
    print(f"\nwrote:\n  {out1}\n  {out2}\n  {out3}\n  {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
