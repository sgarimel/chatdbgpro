"""Mid-session "check my work" judge for the debugging model.

The debugging LLM calls ``check_my_work(diagnosis)`` as a tool whenever it
believes it has found the bug. This module sends the diagnosis to a judge
LLM, which scores it against the pre-registered rubric and returns
targeted feedback so the model can refine its answer *without* leaving the
debugger session.

Stale-check rule: if the per-axis score vector does not improve for
``max_stale_checks`` consecutive calls (default 2), the tool tells the
model to stop and emit its final answer — the orchestrator's outer timeout
is the last-resort fallback.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import litellm

import yaml


# ── Mid-session judge prompts ────────────────────────────────────────

_JUDGE_SYSTEM = """\
You are an expert C/C++ debugging judge embedded in a live debugging session.
A model-under-test is debugging a program and has submitted its current
diagnosis for review. You evaluate it against three pre-registered criteria
and return structured feedback so the model can improve.

You score three independent axes, each 0 or 1:
  1. root_cause  — correct diagnosis of the defect
  2. local_fix   — proposed fix satisfies the local_fix criterion
  3. global_fix  — proposed fix satisfies the global_fix criterion

Rules:
  * Be STRICT. Credit only when the literal criterion is clearly met.
  * For any axis scored 0, give a SHORT, TARGETED hint (1-2 sentences)
    pointing the model toward what it is missing — but do NOT reveal the
    exact answer. Guide, don't solve.
  * For axes scored 1, say "Correct." and nothing more.
  * If the model is completely off-track, say so plainly.

Respond with a single JSON object:
{
  "root_cause": 0 or 1,
  "local_fix": 0 or 1,
  "global_fix": 0 or 1,
  "feedback": {
    "root_cause": "Correct." or a hint,
    "local_fix":  "Correct." or a hint,
    "global_fix": "Correct." or a hint
  }
}

Do NOT wrap in markdown fences. No text before or after the JSON."""

_JUDGE_USER = """\
### Buggy source ({source_file})

```{language}
{source}
```

### Rubric

**root_cause**
{root_cause_criterion}

**local_fix**
{local_fix_criterion}

**global_fix**
{global_fix_criterion}

### Model's current diagnosis

{diagnosis}

### Task

Score against the rubric. For axes scored 0, give a targeted hint."""


# ── Data structures ──────────────────────────────────────────────────

@dataclass
class CheckResult:
    """One mid-session check invocation."""
    check_number: int
    scores: dict[str, int]
    feedback: dict[str, str]
    judge_input_tokens: int = 0
    judge_output_tokens: int = 0
    elapsed_s: float = 0.0
    raw_output: str = ""

    def total_score(self) -> int:
        return sum(self.scores.values())

    def to_dict(self) -> dict:
        return {
            "check_number": self.check_number,
            "scores": self.scores,
            "feedback": self.feedback,
            "judge_input_tokens": self.judge_input_tokens,
            "judge_output_tokens": self.judge_output_tokens,
            "elapsed_s": self.elapsed_s,
        }


@dataclass
class CheckMyWorkState:
    """Tracks all check_my_work calls within one debugging session."""
    checks: list[CheckResult] = field(default_factory=list)
    max_stale_checks: int = 2
    _stale_count: int = 0
    _best_score: int = -1

    @property
    def num_checks(self) -> int:
        return len(self.checks)

    @property
    def is_stale(self) -> bool:
        return self._stale_count >= self.max_stale_checks

    @property
    def is_perfect(self) -> bool:
        if not self.checks:
            return False
        return self.checks[-1].total_score() == 3

    def record(self, result: CheckResult) -> None:
        self.checks.append(result)
        score = result.total_score()
        if score > self._best_score:
            self._best_score = score
            self._stale_count = 0
        else:
            self._stale_count += 1

    def checks_to_axis(self, axis: str) -> int | None:
        """Return the check number (1-indexed) where `axis` first scored 1,
        or None if it never did."""
        for c in self.checks:
            if c.scores.get(axis, 0) == 1:
                return c.check_number
        return None

    def summary(self) -> dict:
        return {
            "num_checks": self.num_checks,
            "final_scores": self.checks[-1].scores if self.checks else {},
            "checks_to_root_cause": self.checks_to_axis("root_cause"),
            "checks_to_local_fix": self.checks_to_axis("local_fix"),
            "checks_to_global_fix": self.checks_to_axis("global_fix"),
            "stale_exit": self.is_stale,
            "history": [c.to_dict() for c in self.checks],
        }


# ── Judge call ───────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    import re
    text = text.strip()
    fence = re.match(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _to01(v: Any) -> int:
    if v in (0, 1):
        return int(v)
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, str):
        v = v.strip().lower()
        return 1 if v in ("1", "true", "yes") else 0
    return 0


def call_judge(
    diagnosis: str,
    *,
    source: str,
    source_file: str,
    language: str,
    criteria: dict[str, str],
    judge_model: str,
    check_number: int,
) -> CheckResult:
    """Call the judge LLM and return a CheckResult."""
    user_prompt = _JUDGE_USER.format(
        source_file=source_file,
        language=language,
        source=source[:20_000],
        root_cause_criterion=criteria.get("root_cause", "(missing)"),
        local_fix_criterion=criteria.get("local_fix", "(missing)"),
        global_fix_criterion=criteria.get("global_fix", "(missing)"),
        diagnosis=diagnosis[:40_000],
    )

    t0 = time.time()
    resp = litellm.completion(
        model=judge_model,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
    )
    elapsed = time.time() - t0

    content = resp.choices[0].message.content or ""
    usage = getattr(resp, "usage", None) or {}
    ptok = getattr(usage, "prompt_tokens", None) or (
        usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
    )
    ctok = getattr(usage, "completion_tokens", None) or (
        usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
    )

    parsed = _extract_json(content)
    if parsed is None:
        return CheckResult(
            check_number=check_number,
            scores={"root_cause": 0, "local_fix": 0, "global_fix": 0},
            feedback={
                "root_cause": "Judge failed to parse — please try again.",
                "local_fix": "Judge failed to parse — please try again.",
                "global_fix": "Judge failed to parse — please try again.",
            },
            judge_input_tokens=ptok,
            judge_output_tokens=ctok,
            elapsed_s=elapsed,
            raw_output=content,
        )

    scores = {
        "root_cause": _to01(parsed.get("root_cause")),
        "local_fix": _to01(parsed.get("local_fix")),
        "global_fix": _to01(parsed.get("global_fix")),
    }
    feedback = parsed.get("feedback", {})

    return CheckResult(
        check_number=check_number,
        scores=scores,
        feedback={
            "root_cause": feedback.get("root_cause", ""),
            "local_fix": feedback.get("local_fix", ""),
            "global_fix": feedback.get("global_fix", ""),
        },
        judge_input_tokens=ptok,
        judge_output_tokens=ctok,
        elapsed_s=elapsed,
        raw_output=content,
    )


# ── Load criteria from case.yaml ─────────────────────────────────────

def load_criteria_from_case_yaml(path: str | Path) -> dict:
    """Return {criteria, source, source_file, language} from a case.yaml."""
    p = Path(path)
    with open(p) as f:
        case = yaml.safe_load(f)

    criteria = case.get("criteria", {})
    language = case.get("language", "c")
    source_file = case.get("source_file", "")

    # Try to read the source file (sibling of case.yaml)
    source = ""
    if source_file:
        src_path = p.parent / source_file
        if src_path.exists():
            try:
                source = src_path.read_text()
            except UnicodeDecodeError:
                source = src_path.read_text(errors="replace")

    # Fallback for injected_repo cases: source lives in workspace cache
    if not source:
        rc_file = (case.get("bug", {}) or {}).get("root_cause_file")
        if rc_file:
            source_file = rc_file
            # Check common locations
            for candidate in [
                p.parent / rc_file,
                p.parent.parent / ".workspace-cache" / case.get("id", "") / rc_file,
            ]:
                if candidate.exists():
                    try:
                        source = candidate.read_text()
                    except UnicodeDecodeError:
                        source = candidate.read_text(errors="replace")
                    break

    return {
        "criteria": criteria,
        "source": source,
        "source_file": source_file,
        "language": language,
    }
