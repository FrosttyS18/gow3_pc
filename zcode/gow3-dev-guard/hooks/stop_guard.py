#!/usr/bin/env python3
"""Stop hook of gow3-dev-guard.

Validates that the final assistant message carries the GOW3 — ZCODE REPORT contract defined
in AGENTS.md: one ```text fenced block, the report header, every required section and every
required field with a non-empty value. Structural check only — it proves the report exists
and is complete, it does not certify that quoted logs are true (that stays with code review).

Loop safety (deterministic, no host cooperation required):
  - stop_hook_active in the payload => pass immediately (the host already continued once);
  - a per-session counter lets the hook block at most 2 times; from the 3rd Stop on it passes
    with a warning, so the session can always end.

Fail-open (exit 0 + warning) when the transcript cannot be read or has no assistant text.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard_common as g  # noqa: E402

REPORT_HEADER = re.compile(r"GOW3\s+[—-]\s+ZCODE\s+REPORT")
FENCED = re.compile(r"```text[^\n]*\n(.*?)```", re.DOTALL)

REQUIRED_SECTIONS = ("TASK", "GIT", "BASELINE", "CHANGES", "VALIDATION", "AUDIT GATE",
                     "FINAL STATUS", "NEXT")
REQUIRED_FIELDS = {
    "TASK": ("Name", "Status"),
    "GIT": ("Branch", "Commit", "Remote"),
    "BASELINE": ("Status", "Reference"),
    "CHANGES": ("Added", "Modified", "Removed", "Files"),
    "VALIDATION": ("Python", "Native", "Build", "Package", "UI", "Runtime"),
    "AUDIT GATE": ("Result", "Regressions", "Evidence"),
    "FINAL STATUS": (),
    "NEXT": (),
}
STATUS_VALUES = ("READY_FOR_REVIEW", "BLOCKED", "FAILED")
MAX_BLOCKS_PER_SESSION = 2


def last_assistant_text(transcript_path: str) -> str | None:
    """The concatenated text of the last assistant message in a JSONL transcript."""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else entry
        role = message.get("role") or entry.get("role")
        if role != "assistant":
            continue
        content = message.get("content")
        texts = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            texts.append("".join(part.get("text", "") for part in content
                                 if isinstance(part, dict) and part.get("type") == "text"))
        text = "\n".join(t for t in texts if t)
        if text.strip():
            return text
    return None


def report_defects(text: str) -> list[str]:
    """Missing/invalid pieces of the final report, in contract order."""
    defects = []
    blocks = FENCED.findall(text)
    block = blocks[-1] if blocks else None
    if block is None:
        return ["no ```text fenced block found — the report must be one text code block"]
    if not REPORT_HEADER.search(block):
        defects.append("missing header 'GOW3 — ZCODE REPORT'")
    for section in REQUIRED_SECTIONS:
        pattern = rf"^\s*{re.escape(section)}\s*$"
        if not re.search(pattern, block, re.MULTILINE):
            defects.append(f"missing section {section}")
    for section, fields in REQUIRED_FIELDS.items():
        for field in fields:
            # Horizontal whitespace only after the colon: \s* would swallow the newline and
            # "validate" an empty value against the next line's content.
            pattern = rf"^\s*{re.escape(field)}:[ \t]*\S"
            if not re.search(pattern, block, re.MULTILINE):
                defects.append(f"missing or empty field {section}.{field}")
    status = re.search(r"^\s*FINAL STATUS\s*\n\s*(\S+)", block, re.MULTILINE)
    if status and status.group(1) not in STATUS_VALUES:
        defects.append(f"FINAL STATUS must be one of {', '.join(STATUS_VALUES)}")
    next_value = re.search(r"^\s*NEXT\s*\n\s*(.+)", block, re.MULTILINE)
    if next_value and not next_value.group(1).strip():
        defects.append("NEXT is empty")
    return defects


def main() -> int:
    payload = g.read_payload()
    if payload is None:
        g.warn("invalid or missing JSON payload; failing open")
        return g.PASS
    if payload.get("stop_hook_active"):
        g.warn("stop_hook_active set by the host: passing to avoid a continuation loop")
        return g.PASS

    counter = g.stop_state_file(payload)
    try:
        count = int(counter.read_text(encoding="utf-8")) if counter.is_file() else 0
    except (OSError, ValueError):
        count = 0
    if count >= MAX_BLOCKS_PER_SESSION:
        g.warn(f"already blocked {count} times in this session; passing so the session can end."
               " The final report is still missing or invalid — fix it in the next message.")
        return g.PASS

    transcript = payload.get("transcript_path") or payload.get("transcriptPath")
    text = last_assistant_text(str(transcript)) if transcript else None
    if text is None:
        g.warn("no readable assistant message in the transcript; failing open")
        return g.PASS

    defects = report_defects(text)
    if not defects:
        try:
            counter.parent.mkdir(parents=True, exist_ok=True)
            counter.write_text("0", encoding="utf-8")  # a valid report resets the counter
        except OSError:
            pass
        return g.PASS

    try:
        counter.parent.mkdir(parents=True, exist_ok=True)
        counter.write_text(str(count + 1), encoding="utf-8")
    except OSError:
        pass
    g.block("STOP — the final message does not satisfy the ZCODE FINAL REPORT CONTRACT"
            f" (AGENTS.md): {'; '.join(defects)}. End the task with the complete report"
            " in a single ```text block.")
    return g.BLOCK


if __name__ == "__main__":
    sys.exit(main())
