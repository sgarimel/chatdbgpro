# Capital-H Hard bugs — research note

A walk through 75 judge-scored agent runs (4 models × 19 cases), focused
on **why** the hard cases stay hard.

## 1. The hardest cases (mean total ≤ 1, 0–3 scale)

| Case | Mean | GPT-5.5 | Nemotron-30B | Qwen-30B | Gemini-FL |
|---|---|---|---|---|---|
| `test-overflow` | **0.75** | 3 | 0 | 0 | 0 |
| `uninit-stack-accumulator` | **0.75** | 3 | 0 | 0 | 0 |

Both are *only* solved by GPT-5.5. Both have **high engagement** from
the failing models — `test-overflow` averages 14 tool calls per
failing run, `uninit-stack-accumulator` averages 23. So this is not a
"didn't try" failure; the models reach for tools, traverse the
debugger, and still fail to produce a usable answer.

## 2. Three distinct failure modes on these H-Hard cases

I read the transcripts for all 4 models on both cases. The failures
factor into three modes that don't overlap:

### Mode A — "Wave the white flag" (Nemotron-30B)
- `test-overflow`: **1 tool call (`bt`)**, response length **1 char** (a single newline).
- `uninit-stack-accumulator`: 4 tool calls, 4-char response.
- The model issues `bt`, sees a stack trace it can't immediately
  interpret, and emits no prose at all. Judge correctly scores 0/0/0.
- Surfaces the model's **inability to reason from a non-trivial stack
  trace alone** — without further engagement the model just gives up.

### Mode B — "Hallucinated sandbox" (Qwen-30B)
- `test-overflow`: 5 tool calls (`bt`, `process`, `target`, `code`),
  2.4K-char response, but the response opens with:
  > *"The debugging session cannot proceed because the necessary LLDB
  > commands (`process status`, `target create`, `bt`) are not
  > permitted. This suggests that the debugging environment is
  > restricted or sandboxed."*
- The commands **were permitted** and **did return data**. Qwen
  misinterprets some lldb output as denial-of-access and bails.
- `uninit-stack-accumulator`: hallucinates a build failure
  (*"Cannot find crt0.o"*, *"Rebuild with debug symbols"*) and writes a
  tutorial about ELF entry points. Binary built fine; ASan flagged
  uninit; Qwen never sees that, decides the env is broken, refuses to
  engage with the actual bug.
- This is a **model-side reliability failure** — Qwen has a learned
  "this looks unfamiliar → blame the environment" reflex.

### Mode C — "Tool-loop, empty answer" (Gemini-3.1-Flash-Lite)
- The most striking finding in the data. Across **9 of 11 zero-score
  runs**, `resp_len ≈ n_tools` (one newline emitted per tool call,
  no prose synthesis):

  ```
  uninit-stack-accumulator     41 tools  →  41-char response (newlines)
  test-overflow                29 tools  →  29-char response
  intoverflow-alloc            24 tools  →  24-char response
  test-definition-likely       23 tools  →  23-char response
  cjson-parse-string-oob       20 tools  →  20-char response
  test-deep-recursion          19 tools  →  19-char response
  double-free-errpath          15 tools  →  15-char response
  stack-buffer-overflow-strcpy 14 tools  →  14-char response
  off-by-one-crc                3 tools  →   3-char response
  ```

  Tool frequencies are diverse — Gemini-FL used `bt`, `frame`,
  `image`, `register`, `disassemble`, `code`, `shell`, `breakpoint`.
  It's *engaging deeply* in the debugger and then **failing to emit a
  final prose answer**, instead emitting one blank line per tool turn.

- The 1 outlier (`test-use-after-free`) gave a 2058-char real answer,
  but still scored 0/3. So even when Gemini-FL synthesizes prose, it
  doesn't get there.

- This is the most publishable finding in the suite: **Gemini-Flash-Lite
  does not reliably synthesize a final-answer prose turn in long
  tool-use conversations.** It looks busy on the inside, returns
  nothing on the outside. A `ls` was the most-frequent "tool" call (17×
  on test-overflow) — this isn't even an lldb command, the model is
  hallucinating shell verbs into the debugger context.

### What GPT-5.5 does differently
- 21 tool calls on `test-overflow`, with diverse verbs:
  `target / thread / image / source / settings / help / platform /
  process / code / definition` — it explores the lldb command space
  rather than fixating on `bt`.
- 38 tool calls on `uninit-stack-accumulator` — willing to spend
  many turns following MSan's report through the source.
- Crucially, it **always closes with prose** that names the defect,
  proposes a fix, and explains why it works. Mode C never happens.

## 3. The "fix-vs-explain" cliff (universal across models)

A different kind of H-Hard: cases where every model patches the bug
correctly but **none** propose the structural fix the criterion asks
for.

| Case | mean root_cause | mean local_fix | mean global_fix |
|---|---|---|---|
| `off-by-one-crc` | 0.75 | 0.75 | **0.00** |
| `null-deref-env` | 1.00 | 1.00 | 0.25 |
| `heap-overflow-csv` | 0.75 | 0.75 | 0.25 |

On `off-by-one-crc` **all four models — including GPT-5.5 — score 0
on global_fix**. They flip `<=` to `<` correctly. None propose the
structural alternatives the criterion asks for (half-open
`[begin, end)` range, `std::span<const uint8_t>`,
length-invariant assertion). The judge's rationale on GPT-5.5:

> *"The response does not propose a structural change such as using a
> half-open range or a bounded view type."*

This is not a model-scale issue. It's a **prompt/criterion mismatch**:
the model is asked "propose a fix in code" and naturally minimizes the
diff. The "design refactor" frame isn't surfaced to the model. A
follow-up turn — *"now propose a structural fix that prevents this
class of bug"* — would almost certainly recover most global_fix
points. Worth wiring as an ablation.

The one counter-example: **Qwen-30B** beat GPT-5.5 on
`heap-overflow-csv` global_fix because it suggested `strndup(line, n)`
— a standard bounded-copy idiom — as an alternative to the local
`malloc(n+1)` patch. GPT-5.5 only suggested the local patch. So Qwen
has *some* structural-design instinct that GPT-5.5 sometimes lacks.

## 4. What "capital-H hard" actually decomposes into

Three independent axes of difficulty in this data:

| Axis | What it tests | Hardest-case | Gap pattern |
|---|---|---|---|
| **A. Multi-step reasoning** | Compose a chain of tool outputs into a defect localization | `test-overflow`, `uninit-stack-accumulator` | GPT-5.5 wins; smaller models exhibit Mode A/B/C |
| **B. Tool-use synthesis** | Actually emit the final prose answer after using tools | (Gemini-FL on most cases) | Model-side reliability bug; not really about debugging at all |
| **C. Design-fix framing** | Propose a structural fix instead of a minimal patch | `off-by-one-crc`, `null-deref-env`, `heap-overflow-csv` | Universal; even GPT-5.5 fails. Likely fixable with a follow-up question. |

Axis A is the project's core motivation argument: "small models +
better interaction structure" cannot match a frontier model on
multi-step reasoning bugs *as currently shaped*. Useful evidence to
keep building on.

Axis B is a model-quality discovery, not a debugging discovery. It
deserves its own one-paragraph note in the report.

Axis C is the most actionable: a tiny harness change (always ask a
follow-up "propose a structural fix") would likely flip ~5-10 cells
across the 4 models and is much easier to land than retraining or
swapping models.

## 5. Suggested next-step experiments (in priority order)

1. **Targeted-question follow-up ablation.** Re-run the cases in §3 with
   a second turn: *"Propose a structural change that prevents this class
   of bug — not just a patch."* Hypothesis: ≥75% of zero-global_fix runs
   recover to 1. Cheapest experiment in this list.

2. **Constrain Gemini-FL's tool budget.** The 41-tool-call empty-prose
   pattern looks like the model exhausting its planning budget on
   tool calls. Cap at ~5 tool calls and see if the prose-synthesis
   recovers. If yes, the model wasn't "too small" — it was being given
   too much rope.

3. **Stack-trace-only baseline for the H-Hard cases.** Re-run
   `test-overflow` and `uninit-stack-accumulator` with `tier3_no_tools`
   so the model must reason from the inline stack trace alone. Compare
   to the tool-enabled scores. Hypothesis: Mode A (Nemotron) actually
   does *better* without tools because it stops trying to drive the
   debugger and just reads the source. Easy to verify; would invert the
   project's "more tools = better" prior.

4. **Failure-mode classifier for the bench.** All three modes (A/B/C)
   are detectable from `(n_tools, resp_len, total_score)` — see §2. A
   small classifier could tag every run as "engaged-and-correct",
   "wave-white-flag", "hallucinated-sandbox", "tool-loop-empty",
   "patched-but-no-design", "saturated". Useful for the report.
