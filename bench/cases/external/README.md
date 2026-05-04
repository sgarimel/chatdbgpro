# External C/C++ Benchmark Imports

This directory contains small, gdb-ready cases copied from external benchmark
checkouts under `external/benchmarks/`.

Imported cases:

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

Regenerate with:

```bash
python scripts/import_external_benchmarks.py
```

The source checkouts are intentionally ignored by git. Recreate them with:

```bash
git clone --depth 1 https://github.com/ortegaalfredo/crashbench.git external/benchmarks/crashbench
git clone --depth 1 https://github.com/arichardson/juliet-test-suite-c.git external/benchmarks/juliet-test-suite-c
git -C external/benchmarks/juliet-test-suite-c config core.longpaths true
git clone --depth 1 https://github.com/codeflaws/codeflaws.git external/benchmarks/codeflaws
```
