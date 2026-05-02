import textwrap

import llm_utils


class _ArgumentEntry:
    def __init__(self, type: str, name: str, value: str):
        self._type = type
        self._name = name
        self._value = value

    def __str__(self):
        return f"({self._type}) {self._name} = {self._value if self._value is not None else '[unknown]'}"

    def __repr__(self):
        return f"_ArgumentEntry({repr(self._type)}, {repr(self._name)}, {repr(self._value) if self._value is not None else '[unknown]'})"


class _FrameSummaryEntry:
    def __init__(
        self,
        index: int,
        name: str,
        arguments: list[_ArgumentEntry],
        file_path: str,
        lineno: int,
    ):
        self._index = index
        self._name = name
        self._arguments = arguments
        self._file_path = file_path
        self._lineno = lineno

    def index(self):
        return self._index

    def file_path(self):
        return self._file_path

    def lineno(self):
        return self._lineno

    def __str__(self):
        a = ", ".join([str(a) for a in self._arguments])
        # Omit the "at file:line" suffix when source info is missing — common
        # for stripped/system frames surfaced by the fallback path.
        if not self._file_path and not self._lineno:
            return f"{self._index}: {self._name}({a})"
        return f"{self._index}: {self._name}({a}) at {self._file_path}:{self._lineno}"

    def __repr__(self):
        return f"_FrameSummaryEntry({self._index}, {repr(self._name)}, {repr(self._arguments)}, {repr(self._file_path)}, {self._lineno})"


class _SkippedFramesEntry:
    def __init__(self, count: int):
        self._count = count

    def count(self):
        return self._count

    def __str__(self):
        return f"[{self._count} skipped frame{'s' if self._count > 1 else ''}...]"

    def __repr__(self):
        return f"_SkippedFramesEntry({self._count})"


def build_enriched_stacktrace(summaries):
    parts = []
    if not summaries:
        print("could not generate any frame summary.")
        return
    else:
        frame_summary = "\n".join([str(s) for s in summaries])
        parts.append(frame_summary)

        total_frames = sum(
            [s.count() if isinstance(s, _SkippedFramesEntry) else 1 for s in summaries]
        )

        if total_frames > 1000:
            parts.append(
                "Note that there are over 1000 frames in the stack trace, hinting at a possible stack overflow error."
            )

    max_initial_locations_to_send = 3
    source_code_entries = []
    for summary in summaries:
        if isinstance(summary, _FrameSummaryEntry):
            file_path, lineno = summary.file_path(), summary.lineno()
            # Source extraction requires both a path and a line number. Frames
            # in the fallback path (libc, stripped) may have neither — skip
            # them rather than crashing on `None - 10`.
            if not file_path or not lineno:
                continue
            lines, first = llm_utils.read_lines(file_path, lineno - 10, lineno + 9)
            block = llm_utils.number_group_of_lines(lines, first)
            block = textwrap.indent(block, "  ")
            source_code_entries.append(
                f"Frame #{summary.index()} at {file_path}:{lineno}:\n{block}\n"
            )

            if len(source_code_entries) == max_initial_locations_to_send:
                break

    if source_code_entries:
        parts.append(
            f"Here is the source code for the first {len(source_code_entries)} frames:\n\n"
            + "\n\n".join(source_code_entries)
        )
    else:
        print("could not retrieve source code for any frames.")
    return "\n\n".join(parts)
