#!/usr/bin/env python3
"""Import low-friction external C/C++ bug benchmarks into bench/cases.

The upstream benchmark checkouts are intentionally kept outside git under
external/benchmarks/. This script copies a small, gdb-friendly subset into
bench/cases/external/ as ordinary synthetic ChatDBG cases.
"""
from __future__ import annotations

import configparser
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
EXTERNAL = REPO / "external" / "benchmarks"
OUT = REPO / "bench" / "cases" / "external"


@dataclass(frozen=True)
class CrashbenchCase:
    source: str
    args: list[str]
    category: str
    error_type: str


CRASHBENCH_CASES = [
    CrashbenchCase("abo1.c", ["A" * 600], "stack_buffer_overflow", "unsafe_strcpy"),
    CrashbenchCase("abo2.c", ["A" * 600], "stack_buffer_overflow", "unsafe_strcpy"),
    CrashbenchCase("abo3.c", ["A" * 600, "hello"], "stack_buffer_overflow", "unsafe_strcpy"),
    CrashbenchCase("abo5.c", ["A" * 600, "B" * 128], "stack_buffer_overflow", "unsafe_strcpy"),
    CrashbenchCase("abo7.c", ["A" * 600], "global_buffer_overflow", "unsafe_strcpy"),
    CrashbenchCase("abo8.c", ["A" * 600], "global_buffer_overflow", "unsafe_strcpy"),
]


@dataclass(frozen=True)
class JulietCase:
    cwe_dir: str
    source_rel: str
    category: str
    error_type: str
    local_fix_hint: str
    global_fix_hint: str


JULIET_CASES = [
    JulietCase(
        "CWE121_Stack_Based_Buffer_Overflow",
        "s01/CWE121_Stack_Based_Buffer_Overflow__char_type_overrun_memcpy_01.c",
        "stack_buffer_overflow",
        "type_overrun_memcpy",
        "Use sizeof(structCharVoid.charFirst), not sizeof(structCharVoid), as the memcpy length.",
        "Represent the destination as a bounded buffer/span so copy length is tied to the field capacity.",
    ),
    JulietCase(
        "CWE122_Heap_Based_Buffer_Overflow",
        "s01/CWE122_Heap_Based_Buffer_Overflow__char_type_overrun_memcpy_01.c",
        "heap_buffer_overflow",
        "type_overrun_memcpy",
        "Allocate and copy only sizeof(structCharVoid.charFirst) bytes for the character field.",
        "Use a bounded field copy helper or typed buffer wrapper so struct size cannot be confused with field size.",
    ),
    JulietCase(
        "CWE126_Buffer_Overread",
        "s01/CWE126_Buffer_Overread__char_alloca_loop_01.c",
        "buffer_overread",
        "missing_null_termination",
        "Ensure the source string is null-terminated before printing or bound the read by the buffer length.",
        "Pass explicit lengths through the API instead of relying on sentinel-terminated raw buffers.",
    ),
    JulietCase(
        "CWE415_Double_Free",
        "s01/CWE415_Double_Free__malloc_free_char_01.c",
        "double_free",
        "free_twice",
        "Remove the second free or set the pointer to NULL immediately after ownership is released.",
        "Adopt a single-owner cleanup pattern so each allocation has one responsible free site.",
    ),
    JulietCase(
        "CWE416_Use_After_Free",
        "CWE416_Use_After_Free__malloc_free_char_01.c",
        "use_after_free",
        "dangling_pointer_read",
        "Do not use the buffer after free; move the read/print before free or keep it allocated until after use.",
        "Make object lifetime explicit with ownership conventions or RAII-style wrappers.",
    ),
]


def _clean_external_cases() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for child in OUT.iterdir():
        if child.is_dir() and (child.name.startswith("crashbench-") or child.name.startswith("juliet-")):
            shutil.rmtree(child)


def _yaml_list(values: list[str]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(repr(v).replace("'", '"') for v in values) + "]"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _crashbench_line_map(config_path: Path) -> dict[str, int]:
    parser = configparser.ConfigParser()
    parser.read(config_path)
    out: dict[str, int] = {}
    for section in parser.sections():
        if section == "SETTINGS":
            continue
        for _, value in parser.items(section):
            filename, line = value.rsplit(",", 1)
            if filename.endswith(".c"):
                out[Path(filename).name] = int(line)
    return out


def import_crashbench() -> list[str]:
    root = EXTERNAL / "crashbench"
    if not root.exists():
        raise FileNotFoundError(
            "Missing external/benchmarks/crashbench. Run: "
            "git clone --depth 1 https://github.com/ortegaalfredo/crashbench.git "
            "external/benchmarks/crashbench"
        )
    line_map = _crashbench_line_map(root / "config.ini")
    imported: list[str] = []
    for case in CRASHBENCH_CASES:
        src = root / "tests" / case.source
        case_id = f"crashbench-{Path(case.source).stem}"
        dst = OUT / case_id
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst / "program.c")
        bug_line = line_map[case.source]
        args = _yaml_list(case.args)
        _write_text(dst / "case.yaml", f"""id: {case_id}
language: c
source_file: program.c
description: >
  Imported from Crashbench's C test corpus. The program is built with
  debug symbols and AddressSanitizer so gdb stops at the concrete memory
  safety failure instead of relying on static review.

build:
  compiler: clang
  flags: ["-g", "-O0", "-std=gnu89", "-fno-omit-frame-pointer", "-fsanitize=address", "-no-pie", "-Wno-implicit-function-declaration", "-Wno-int-conversion", "-Wno-return-type", "-Wno-builtin-requires-header"]

run:
  args: {args}
  stdin: ""
  env: {{}}
  expected_crash: true

bug:
  benchmark: crashbench
  upstream_file: tests/{case.source}
  upstream_expected_line: {bug_line}
  category: {case.category}
  error_type: {case.error_type}
  root_cause_lines: [{bug_line}]
  related_lines: []

criteria:
  root_cause: >
    The response must identify the unsafe copy at Crashbench's expected
    bug line {bug_line}, explain that attacker-controlled argv data can
    exceed the destination buffer, and name the resulting {case.category}.
    Merely saying "the program crashed" or only repeating the sanitizer
    class without localizing the copy does not count.

  local_fix: >
    Replace the unbounded copy with a length-checked copy sized to the
    destination buffer, reject overlong input before copying, and ensure
    the destination remains null-terminated.

  global_fix: >
    A root-cause fix removes raw, unbounded string handling from the data
    path: carry buffer capacities with pointers, use a bounded string API,
    or centralize argv validation before any copy into fixed storage.
""")
        imported.append(case_id)
    return imported


def _first_flaw_line(path: Path) -> int:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for idx, line in enumerate(lines, start=1):
        if "FLAW:" in line:
            for j in range(idx + 1, len(lines) + 1):
                stripped = lines[j - 1].strip()
                if stripped and not stripped.startswith("/*") and not stripped.startswith("*"):
                    return j
            return idx
    return 1


def _copy_juliet_support(dst: Path, source_root: Path) -> None:
    support = source_root / "testcasesupport"
    shutil.copy(support / "io.c", dst / "io.c")
    shutil.copy(support / "std_testcase.h", dst / "std_testcase.h")
    shutil.copy(support / "std_testcase_io.h", dst / "std_testcase_io.h")


def import_juliet() -> list[str]:
    root = EXTERNAL / "juliet-test-suite-c"
    if not root.exists():
        raise FileNotFoundError(
            "Missing external/benchmarks/juliet-test-suite-c. Run: "
            "git clone --depth 1 https://github.com/arichardson/juliet-test-suite-c.git "
            "external/benchmarks/juliet-test-suite-c"
        )
    imported: list[str] = []
    for case in JULIET_CASES:
        src = root / "testcases" / case.cwe_dir / case.source_rel
        stem = Path(case.source_rel).stem
        short = re.sub(r"^CWE(\d+)_.*__", r"cwe\1-", stem).lower().replace("_", "-")
        case_id = f"juliet-{short}"
        dst = OUT / case_id
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst / "program.c")
        _copy_juliet_support(dst, root)
        bug_line = _first_flaw_line(src)
        _write_text(dst / "case.yaml", f"""id: {case_id}
language: c
source_file: program.c
description: >
  Imported from the NIST Juliet C/C++ 1.3 suite via the Unix-friendly
  arichardson/juliet-test-suite-c mirror. The case is compiled as the
  standalone bad variant only.

build:
  compiler: clang
  flags: ["-g", "-O0", "-std=gnu99", "-fno-omit-frame-pointer", "-fsanitize=address", "-Wno-unused-function"]
  defines: ["INCLUDEMAIN", "OMITGOOD"]
  include_dirs: ["."]
  extra_sources: ["io.c"]
  support_files: ["std_testcase.h", "std_testcase_io.h"]

run:
  args: []
  stdin: ""
  env: {{}}
  expected_crash: true

bug:
  benchmark: juliet-c-cpp-1.3
  upstream_file: testcases/{case.cwe_dir}/{case.source_rel}
  category: {case.category}
  error_type: {case.error_type}
  root_cause_lines: [{bug_line}]
  related_lines: []

criteria:
  root_cause: >
    The response must identify the bad Juliet variant's FLAW site around
    line {bug_line} and explain the concrete {case.category} mechanism in
    this file. Naming only the CWE number or sanitizer class is not enough.

  local_fix: >
    {case.local_fix_hint}

  global_fix: >
    {case.global_fix_hint}
""")
        imported.append(case_id)
    return imported


def main() -> int:
    _clean_external_cases()
    imported = []
    imported.extend(import_crashbench())
    imported.extend(import_juliet())
    _write_text(OUT / "README.md", f"""# External C/C++ Benchmark Imports

This directory contains small, gdb-ready cases copied from external benchmark
checkouts under `external/benchmarks/`.

Imported cases:

{chr(10).join(f"- `{case_id}`" for case_id in imported)}

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
""")
    print(f"Imported {len(imported)} external benchmark cases into {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
