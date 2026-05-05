# T3 Rerun and Judging Handoff

Captured on 2026-05-04 for the external native/non-BugsC++ benchmark work.

## Current Goal

Rerun Tier 3 after the prompt and permission updates, then rerun judging and regenerate the visualization artifacts for the external native bug set.

The external native bug set has exactly 11 test cases:

- `crashbench-abo1`
- `crashbench-abo2`
- `crashbench-abo3`
- `crashbench-abo5`
- `crashbench-abo7`
- `crashbench-abo8`
- `juliet-cwe121-char-type-overrun-memcpy-01`
- `juliet-cwe122-char-type-overrun-memcpy-01`
- `juliet-cwe126-char-alloca-loop-01`
- `juliet-cwe415-malloc-free-char-01`
- `juliet-cwe416-malloc-free-char-01`

These are the non-BugsC++ cases under `bench/cases/external`. Docker should not be used for these cases.

## Repo State

Windows working tree was on:

```text
5a2a0bae bench: allow native T3 config selection
```

That commit was pushed to `origin/main`.

It adds `--tier3-config` to `bench/external_runner.py`, so the native external runner can explicitly use the updated Tier 3 tool config without changing the old default.

The WSL clone at `/root/chatdbgpro` was also pulled to the same commit.

There are unrelated local Windows working tree changes, mostly poster/FAQ assets and `CLAUDE.md`. Do not revert or accidentally commit those unless the user explicitly asks.

## Important T3 Config Detail

The active rerun uses:

```text
--tier3-config t3_unfenced_cmw.json
```

That config enables native debug tools, code surrounding, definition lookup, and check-my-work, while keeping bash disabled:

```json
{
  "enable_native_debug": true,
  "enable_get_code_surrounding": true,
  "enable_find_definition": true,
  "enable_oracle": false,
  "enable_bash": false,
  "enable_check_my_work": true
}
```

The T3 driver already includes the prompt/permission updates:

- `CHATDBG_UNSAFE=true`
- `CHATDBG_PROMPT_SOURCE_FILE`
- `CHATDBG_PROMPT_BEHAVIOR`
- `CHATDBG_PROMPT_DESCRIPTION`
- Check-my-work environment when enabled:
  - `CHATDBG_CMW_CASE_YAML`
  - `CHATDBG_CMW_JUDGE_MODEL`
  - `CHATDBG_CMW_MAX_STALE`

## Live T3 Rerun State

The rerun was launched in WSL as five separate processes, one per model:

- `external-native-t3-rerun-20260504-gpt55`
- `external-native-t3-rerun-20260504-sonnet45`
- `external-native-t3-rerun-20260504-qwen30`
- `external-native-t3-rerun-20260504-gemini31fl`
- `external-native-t3-rerun-20260504-nemotron30`

At the last status check, the processes were still running. Progress was:

```text
external-native-t3-rerun-20260504-gemini31fl dirs=4 ok=2 non_ok=1
external-native-t3-rerun-20260504-gpt55      dirs=3 ok=2 non_ok=0
external-native-t3-rerun-20260504-nemotron30 dirs=3 ok=2 non_ok=0
external-native-t3-rerun-20260504-qwen30     dirs=7 ok=6 non_ok=0
external-native-t3-rerun-20260504-sonnet45   dirs=1 ok=0 non_ok=0
```

The active process list at that point showed:

```text
.venv/bin/python -m bench.external_runner ... --models openrouter/openai/gpt-5.5 ... --name external-native-t3-rerun-20260504-gpt55 --tier3-config t3_unfenced_cmw.json
.venv/bin/python -m bench.external_runner ... --models openrouter/anthropic/claude-sonnet-4.5 ... --name external-native-t3-rerun-20260504-sonnet45 --tier3-config t3_unfenced_cmw.json
.venv/bin/python -m bench.external_runner ... --models openrouter/qwen/qwen3-30b-a3b-instruct-2507 ... --name external-native-t3-rerun-20260504-qwen30 --tier3-config t3_unfenced_cmw.json
.venv/bin/python -m bench.external_runner ... --models openrouter/google/gemini-3.1-flash-lite-preview ... --name external-native-t3-rerun-20260504-gemini31fl --tier3-config t3_unfenced_cmw.json
.venv/bin/python -m bench.external_runner ... --models openrouter/nvidia/nemotron-3-nano-30b-a3b ... --name external-native-t3-rerun-20260504-nemotron30 --tier3-config t3_unfenced_cmw.json
```

Logs are in:

```text
/root/chatdbgpro/bench/results/_logs/external-native-t3-rerun-20260504-*.log
```

The result directories are in:

```text
/root/chatdbgpro/bench/results/external-native-t3-rerun-20260504-*
```

## Check Whether T3 Finished

Run this from Windows PowerShell:

```powershell
$script = @'
cd /root/chatdbgpro
printf 'processes:\n'
ps -eo pid,etime,cmd | grep bench.external_runner | grep -v grep || true
printf '\nrun dirs:\n'
for d in bench/results/external-native-t3-rerun-20260504-*; do
  [ -d "$d" ] || continue
  n=$(find "$d" -mindepth 1 -maxdepth 1 -type d | wc -l)
  ok=$(find "$d" -name result.json -exec grep -l '"status": "ok"' {} \; | wc -l)
  nonok=$(find "$d" -name result.json ! -exec grep -q '"status": "ok"' {} \; -print | wc -l)
  printf '%s dirs=%s ok=%s non_ok=%s\n' "$(basename "$d")" "$n" "$ok" "$nonok"
done
'@
$path = Join-Path $env:TEMP 'chatdbg_t3_status.sh'
[System.IO.File]::WriteAllText($path, $script.Replace("`r`n","`n"), [System.Text.Encoding]::ASCII)
wsl -d Ubuntu bash /mnt/c/Users/Owner/AppData/Local/Temp/chatdbg_t3_status.sh
```

Completion target: each of the five rerun dirs should have 11 attempted run subdirectories. Some may be `timeout` or `error`; that is acceptable as long as each model attempted all 11 cases and wrote `index.json`.

## If a Runner Is Still Hanging

Inspect the specific log first:

```bash
cd /root/chatdbgpro
tail -80 bench/results/_logs/external-native-t3-rerun-20260504-sonnet45.log
```

If a process is clearly stuck beyond the intended timeout behavior, stop only that specific PID and rerun that model with `--skip-existing`.

Template:

```bash
cd /root/chatdbgpro
.venv/bin/python -m bench.external_runner \
  --cases crashbench-abo1 crashbench-abo2 crashbench-abo3 crashbench-abo5 crashbench-abo7 crashbench-abo8 \
          juliet-cwe121-char-type-overrun-memcpy-01 juliet-cwe122-char-type-overrun-memcpy-01 \
          juliet-cwe126-char-alloca-loop-01 juliet-cwe415-malloc-free-char-01 juliet-cwe416-malloc-free-char-01 \
  --models openrouter/anthropic/claude-sonnet-4.5 \
  --tiers 3 \
  --trials 1 \
  --context-lines 10 \
  --timeout 300 \
  --name external-native-t3-rerun-20260504-sonnet45 \
  --tier3-config t3_unfenced_cmw.json \
  --skip-existing
```

Swap the model and run name as needed.

## Merge the New T3 Results

Once the T3 reruns are complete, create a new merged suite that keeps the existing T1/T2/T4 results and replaces only T3.

Suggested target:

```text
/root/chatdbgpro/bench/results/external-native-ablation-20260504-merged-t3rerun
```

Reasonable merge approach:

1. Copy the old merged suite.
2. Remove old Tier 3 run directories from the copy.
3. Copy in all directories from the five `external-native-t3-rerun-20260504-*` result roots.
4. Rebuild `index.json` from the copied run dirs' `result.json` files.
5. Remove all stale `score.json` files if the goal is to fully rerun judging.

Be careful not to overwrite the original:

```bash
cd /root/chatdbgpro
src=bench/results/external-native-ablation-20260504-merged
dst=bench/results/external-native-ablation-20260504-merged-t3rerun
rm -rf "$dst"
cp -a "$src" "$dst"
find "$dst" -mindepth 1 -maxdepth 1 -type d -name '*tier3*' -exec rm -rf {} +
for root in bench/results/external-native-t3-rerun-20260504-*; do
  find "$root" -mindepth 1 -maxdepth 1 -type d -exec cp -a {} "$dst"/ \;
done
find "$dst" -name score.json -delete
.venv/bin/python - <<'PY'
import json
from pathlib import Path
dst = Path("bench/results/external-native-ablation-20260504-merged-t3rerun")
rows = []
for result_path in sorted(dst.glob("*/result.json")):
    rows.append(json.loads(result_path.read_text()))
(dst / "index.json").write_text(json.dumps(rows, indent=2))
print(f"wrote {len(rows)} rows to {dst / 'index.json'}")
PY
```

Expected row count should be close to the prior merged suite count of 187, but it can differ if the original suite included missing-dependency rows that were represented only in `index.json` rather than run directories. If preserving exact index-level missing-dependency rows matters, rebuild by taking the old `index.json` rows where `tier != 3` and appending the new T3 rerun rows.

## Rerun Judging

After merging, rerun the judge on the new merged suite:

```bash
cd /root/chatdbgpro
.venv/bin/python bench/judge.py \
  bench/results/external-native-ablation-20260504-merged-t3rerun \
  --judge-model openrouter/openai/gpt-5
```

If OpenRouter returns a credit or rate-limit error, preserve the partial scores and note exactly how many `score.json` files were produced:

```bash
find bench/results/external-native-ablation-20260504-merged-t3rerun -name score.json | wc -l
```

## Regenerate Analysis and Visualizations

After judging:

```bash
cd /root/chatdbgpro
.venv/bin/python bench/analyze.py bench/results/external-native-ablation-20260504-merged-t3rerun
.venv/bin/python bench/charts.py bench/results/external-native-ablation-20260504-merged-t3rerun
.venv/bin/python bench/visualize.py \
  --results-dir bench/results/external-native-ablation-20260504-merged-t3rerun \
  --output bench/results/external-native-ablation-20260504-merged-t3rerun/analysis/visualize_existing
.venv/bin/python bench/analysis_artifacts/build_cross_tier_pdf.py \
  --suite bench/results/external-native-ablation-20260504-merged-t3rerun \
  --out bench/results/external-native-ablation-20260504-merged-t3rerun/analysis/cross_tier_existing.pdf
```

The chart goal is:

- Heatmap of scores with 12 columns grouped into 4 tier groups of 3 rubric dimensions: root cause, local fix, global fix.
- Average debugging scores by model as a bar chart.
- Average tokens by model as a bar chart.

## Copy Results Back to Windows

When the merged rerun suite is ready:

```bash
cp -a /root/chatdbgpro/bench/results/external-native-ablation-20260504-merged-t3rerun \
  /mnt/c/Users/Owner/OneDrive/Documents/Classes/COS/COS484/chatdbgpro/bench/results/
```

Do this after judging and chart generation so the Windows repo copy has the final PDFs/PNGs/JSONs.

## Notes for Claude

- Do not use Docker for the external native/non-BugsC++ cases.
- Use WSL for the native runner, because Tier 2 and Tier 3 need native Unix-style debugger behavior.
- Do not disturb unrelated Windows working tree changes unless the user asks.
- The committed runner change is already pushed; no need to reimplement it.
- The slow part is model execution, especially Sonnet. Let existing jobs finish unless logs show a true stall.
