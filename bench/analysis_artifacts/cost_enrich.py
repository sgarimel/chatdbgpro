"""Compute estimated USD cost per run from token counts × OpenRouter pricing.

LiteLLM's built-in cost tracking misses many OpenRouter models
(gpt-5.5, gemini-3.1-flash-lite, nemotron-3-nano-30b, grok-4
sometimes via BYOK), so collect.json's `stats.cost` is often `0.0`.
We post-process by:

  1. Pulling live pricing from OpenRouter's `/api/v1/models` once
     per script invocation (cached in a JSON file alongside).
  2. For each `collect.json` under bench/results/<suite>/<run>/:
     read `prompt_tokens` + `completion_tokens` × the model's rate.
  3. Patching the run's `collect.json` with `stats.cost_estimated_usd`
     and a `stats.cost_source` field so analyses can distinguish
     LiteLLM-reported costs from our token-based estimates.

For Tier 4 (Claude Code), the `claude_events.jsonl` result event
has `total_cost_usd`. With keychain/subscription auth that's `0`
(billed against subscription quota); with API-key auth it's the
real figure. We surface both — the reported `total_cost_usd` and
our token-based estimate against Anthropic's published rates so
sweeps comparing API-key cost to subscription have an apples-to-
apples view.

Output: a `costs.csv` aggregated across every result dir with one
row per run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = REPO_ROOT / "bench" / "analysis_artifacts" / "openrouter_pricing.json"

# Anthropic published pricing (per 1M tokens) — for Tier 4 estimates
# when keychain auth reports $0. Keep this in sync with
# https://docs.anthropic.com/en/docs/about-claude/pricing.
ANTHROPIC_PRICING = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-sonnet-4-6-20251122": (3.00, 15.00),
    "sonnet": (3.00, 15.00),     # alias
    "claude-haiku-4-5": (0.25, 1.25),
    "claude-haiku-4-5-20251001": (0.25, 1.25),
    "haiku": (0.25, 1.25),       # alias
    "claude-opus-4-7": (15.00, 75.00),
    "opus": (15.00, 75.00),       # alias
}


def _normalize_model_id(m: str) -> str:
    """Map our model strings to OpenRouter IDs.

    Our convention: `openrouter/<provider>/<model>`. OpenRouter's
    /v1/models endpoint returns IDs as `<provider>/<model>` (no
    `openrouter/` prefix). Strip the prefix when present.
    """
    if not m:
        return m
    if m.startswith("openrouter/"):
        return m[len("openrouter/"):]
    return m


def fetch_openrouter_pricing(api_key: str | None = None,
                              cache_max_age_s: int = 24*3600) -> dict[str, tuple[float, float]]:
    """Return {openrouter_id: (input_$per_M, output_$per_M)}.

    Cached at `openrouter_pricing.json` for 24h to avoid hammering
    the API on every analysis pass."""
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if CACHE_PATH.exists():
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age < cache_max_age_s:
            return _parse_models(json.loads(CACHE_PATH.read_text()))
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models", headers=headers,
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8")
    CACHE_PATH.write_text(body)
    return _parse_models(json.loads(body))


def _parse_models(payload) -> dict[str, tuple[float, float]]:
    pricing: dict[str, tuple[float, float]] = {}
    models = payload.get("data", payload) if isinstance(payload, dict) else payload
    for m in models:
        mid = m.get("id", "")
        p = m.get("pricing", {}) or {}
        try:
            pin = float(p.get("prompt", 0)) * 1e6
            pout = float(p.get("completion", 0)) * 1e6
        except (TypeError, ValueError):
            continue
        if pin or pout:
            pricing[mid] = (pin, pout)
    return pricing


def estimate_cost(prompt_tokens: int, completion_tokens: int,
                  pin_per_M: float, pout_per_M: float) -> float:
    """Compute USD cost from token counts and per-1M-token rates."""
    return ((prompt_tokens or 0) * pin_per_M + (completion_tokens or 0) * pout_per_M) / 1e6


def _model_pricing_for(model: str, openrouter_pricing: dict) -> tuple[float, float, str] | None:
    """Resolve pricing for a model string. Returns (in_per_M,
    out_per_M, source) or None if unknown."""
    or_id = _normalize_model_id(model)
    if or_id in openrouter_pricing:
        pin, pout = openrouter_pricing[or_id]
        return pin, pout, "openrouter"
    # Tier 4 stores the resolved model name (e.g. `claude-sonnet-4-6`)
    # without provider prefix in collect.json's meta.
    bare = model.split("/")[-1] if "/" in model else model
    if bare in ANTHROPIC_PRICING:
        pin, pout = ANTHROPIC_PRICING[bare]
        return pin, pout, "anthropic_published"
    # Try the bare name against OpenRouter
    for prefix in ("anthropic/", "openai/", "google/", "qwen/", "x-ai/", "nvidia/"):
        cand = prefix + bare
        if cand in openrouter_pricing:
            pin, pout = openrouter_pricing[cand]
            return pin, pout, "openrouter"
    return None


def enrich_run(run_dir: Path, openrouter_pricing: dict) -> dict | None:
    """Patch collect.json's stats with cost_estimated_usd. Returns a
    summary row or None if no collect.json."""
    coll_path = run_dir / "collect.json"
    res_path = run_dir / "result.json"
    if not (coll_path.exists() and res_path.exists()):
        return None
    try:
        c = json.loads(coll_path.read_text())
        r = json.loads(res_path.read_text())
    except json.JSONDecodeError:
        return None
    queries = c.get("queries") or []
    if not queries:
        return None
    q = queries[0]
    stats = q.get("stats") or {}
    model = c.get("meta", {}).get("model") or r.get("model") or ""
    p_tok = int(stats.get("prompt_tokens", 0) or 0)
    c_tok = int(stats.get("completion_tokens", 0) or 0)

    # Tier 4 also has a real claude-reported cost in stats.cost
    # (from the result event). Surface both.
    reported_cost = float(stats.get("cost", 0.0) or 0.0)

    pricing_lookup = _model_pricing_for(model, openrouter_pricing)
    if pricing_lookup is None:
        estimated_cost = 0.0
        cost_source = "unknown"
    else:
        pin, pout, cost_source = pricing_lookup
        estimated_cost = estimate_cost(p_tok, c_tok, pin, pout)

    # Patch collect.json (additive — keep stats.cost as-is)
    stats["cost_estimated_usd"] = round(estimated_cost, 6)
    stats["cost_source"] = cost_source
    q["stats"] = stats
    coll_path.write_text(json.dumps(c, indent=2))

    return {
        "suite": run_dir.parent.name,
        "case_id": r.get("case_id"),
        "model": model,
        "tier": r.get("tier"),
        "status": r.get("status"),
        "prompt_tokens": p_tok,
        "completion_tokens": c_tok,
        "total_tokens": p_tok + c_tok,
        "cost_reported_usd": reported_cost,
        "cost_estimated_usd": round(estimated_cost, 6),
        "cost_source": cost_source,
        "elapsed_s": r.get("elapsed_s"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("suites", nargs="*", default=None,
                   help="Suites under bench/results/ to enrich. Default = all.")
    p.add_argument("--out-csv", type=Path,
                   default=REPO_ROOT/"bench"/"analysis_artifacts"/"costs.csv",
                   help="Aggregate per-run cost CSV.")
    args = p.parse_args()

    pricing = fetch_openrouter_pricing()
    print(f"[cost_enrich] OpenRouter pricing has {len(pricing)} models")

    results_root = REPO_ROOT / "bench" / "results"
    suites = ([results_root / s for s in args.suites]
              if args.suites else
              [d for d in results_root.iterdir() if d.is_dir()])

    rows = []
    for suite in suites:
        if not suite.exists():
            print(f"[cost_enrich] skip missing: {suite}")
            continue
        for run in suite.iterdir():
            if not run.is_dir(): continue
            row = enrich_run(run, pricing)
            if row: rows.append(row)
    print(f"[cost_enrich] enriched {len(rows)} runs")

    # Write CSV
    if rows:
        import csv
        cols = list(rows[0].keys())
        with args.out_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"[cost_enrich] wrote {args.out_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
