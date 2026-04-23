"""Parse and reverse git-format unified diffs from BugsC++ taxonomy patches.

BugsC++ ships per-bug patches at taxonomy/<project>/patch/<NNNN>-buggy.patch.
These are git-format-patch outputs whose direction is FIXED -> BUGGY:
  '-' lines = correct (fixed) code
  '+' lines = buggy code

`parse_unified_diff` walks the file/hunk headers and returns one entry per
hunk with the file path (a/ or b/ prefix stripped) and the line range on
the POST-IMAGE side of the hunk (the '+A,B' side).

`reverse_patch` swaps a patch's direction so we can turn a buggy.patch into
the developer FIX patch (BUGGY -> FIXED) that we ship as the ground truth
in data/patches/<bug_id>.diff.
"""
from __future__ import annotations

import re

_FILE_HDR_RE  = re.compile(r"^([-+]{3})\s(.+?)(?:\t.*)?$")
_HUNK_HDR_RE  = re.compile(
    r"^@@\s-(\d+)(?:,(\d+))?\s\+(\d+)(?:,(\d+))?\s@@(.*)$"
)


def _strip_ab_prefix(path: str) -> str:
    """Drop a leading 'a/' or 'b/' from a git-style header path. /dev/null passes through."""
    if path == "/dev/null":
        return path
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def parse_unified_diff(patch_text: str) -> list[dict]:
    """Return [{file, start, end}, ...] one entry per hunk.

    `file` is the in-project path (a/ or b/ prefix stripped) taken from
    the '+++' header. `start`/`end` are line numbers on the POST-IMAGE
    side of the hunk (the '+A,B' header). For a buggy.patch (FIXED ->
    BUGGY direction), those are line numbers in the BUGGY tree.

    Hunks against /dev/null (pure additions or pure deletions where one
    side is the empty file) are skipped on the side we'd otherwise key by.
    """
    out: list[dict] = []
    current_file: str | None = None

    for line in patch_text.splitlines():
        m = _FILE_HDR_RE.match(line)
        if m:
            marker, path = m.group(1), m.group(2).strip()
            if marker == "+++":
                stripped = _strip_ab_prefix(path)
                current_file = None if stripped == "/dev/null" else stripped
            continue

        m = _HUNK_HDR_RE.match(line)
        if not m or current_file is None:
            continue

        plus_start = int(m.group(3))
        plus_count = int(m.group(4)) if m.group(4) is not None else 1
        if plus_count <= 0:
            # Pure deletion: nothing exists on the post-image side.
            # Skip — there's no in-buggy-tree line to anchor.
            continue
        out.append({
            "file":  current_file,
            "start": plus_start,
            "end":   plus_start + plus_count - 1,
        })
    return out


def first_file_and_line(ranges: list[dict]) -> tuple[str | None, int | None]:
    if not ranges:
        return None, None
    r = ranges[0]
    return r["file"], r["start"]


def reverse_patch(patch_text: str) -> str:
    """Swap a unified diff's direction (FIXED<->BUGGY).

    Transformations:
      - '--- X' / '+++ Y'  -> '--- Y' / '+++ X'
      - '@@ -A,B +C,D @@'  -> '@@ -C,D +A,B @@'
      - body line '-foo'   -> '+foo'
      - body line '+foo'   -> '-foo'
      - body line ' foo'   unchanged (context)
      - everything else (commit headers, '\\ No newline at end of file',
        diff --git, index, blank, etc.) passes through verbatim.

    File-header swapping uses a small two-line buffer because '---' and
    '+++' come as a pair.
    """
    lines = patch_text.splitlines(keepends=False)
    out: list[str] = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        # Pair-swap '--- X\n+++ Y' -> '--- Y\n+++ X'
        if (line.startswith("--- ") and i + 1 < n
                and lines[i + 1].startswith("+++ ")):
            minus_path = line[4:]
            plus_path  = lines[i + 1][4:]
            out.append("--- " + plus_path)
            out.append("+++ " + minus_path)
            i += 2
            continue

        m = _HUNK_HDR_RE.match(line)
        if m:
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            tail = m.group(5) or ""

            def _fmt(start: int, count: int) -> str:
                return f"{start}" if count == 1 else f"{start},{count}"

            out.append(
                f"@@ -{_fmt(new_start, new_count)} "
                f"+{_fmt(old_start, old_count)} @@{tail}"
            )
            i += 1
            continue

        # Body lines: only '+'/'-' get swapped. Everything else (' ' context,
        # '\ No newline at end of file', headers we didn't pair, blanks)
        # passes through. Crucially, '+++' / '---' that aren't part of a
        # paired file header (rare) would already be handled above.
        if line.startswith("+") and not line.startswith("+++"):
            out.append("-" + line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            out.append("+" + line[1:])
        else:
            out.append(line)
        i += 1

    # Preserve trailing newline if the input had one.
    trailing = "\n" if patch_text.endswith("\n") else ""
    return "\n".join(out) + trailing
