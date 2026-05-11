# Synthetic T1 — early diagnostics (Anika)
Sweep glob: `bench/results/anika-paper-final-synthetic-20260510-T1-*`
All cells are pre-judge; the judge step is deferred until both panels finish.

## Per-model coverage + format compliance
| Model | N | ok | timeout | no_collect | full RC/LF/GF | partial prose | empty |
|---|---:|---:|---:|---:|---:|---:|---:|
| anthropic claude sonnet 4 5 | 16 | 16 | 0 | 0 | 16 | 0 | 0 |
| google gemini 3 1 flash lite preview | 16 | 16 | 0 | 0 | 5 | 0 | 11 |
| meta llama llama 3 1 8b instruct | 20 | 18 | 2 | 0 | 16 | 2 | 2 |
| nvidia nemotron 3 nano 30b a3b | 16 | 1 | 15 | 0 | 2 | 0 | 14 |
| openai gpt 4o | 20 | 16 | 4 | 0 | 7 | 0 | 13 |
| openai gpt 5 5 | 12 | 12 | 0 | 0 | 12 | 0 | 0 |
| qwen qwen3 30b a3b instruct 2507 | 12 | 11 | 1 | 0 | 8 | 0 | 4 |
| x ai grok 4 | 16 | 14 | 2 | 0 | 12 | 1 | 3 |
| **TOTAL** | **128** | **104** | **24** | **0** | **78** | **3** | **47** |
