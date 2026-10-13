#!/usr/bin/env python3
"""Stop hook of gow3-dev-guard (hardened after the independent audit of 7e85be1).

Validates that the final assistant message satisfies the ZCODE FINAL REPORT CONTRACT
(AGENTS.md): exactly one ```text fenced block, the report header, every required section —
including RISKS — and every required field, each checked inside its own section, with a
non-empty value. Structural check only: it proves the report exists and is complete, not
that quoted logs are true (code review and CI stay owners of content).

Message source (audit item 5): the host-provided `last_assistant_message` field takes
priority, with the transcript (JSONL) as fallback.

Loop safety (deterministic, host-independent): `stop_hook_active` passes at once; a
per-session counter blocks at most 2 times (the host itself caps continuations); a valid
report resets the counter. Unreadable input fails open — Stop must never trap a session.
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
                     "RISKS", "FINAL STATUS", "NEXT")
REQUIRED_FIELDS = {
    "TASK": ("Name", "Status"),
    "GIT": ("Branch", "Commit", "Remote"),
    "BASELINE": ("Status", "Reference"),
    "CHANGES": ("Added", "Modified", "Removed", "Files"),
    "VALIDATION": ("Python", "Native", "Build", "Package", "UI", "Runtime"),
    "AUDIT GATE": ("Result", "Regressions", "Evidence"),
}
SECTION_HEADER = re.compile(
    r"^\s*(" + "|".join(re.escape(section) for section in REQUIRED_SECTIONS) + r")\s*$")
STATUS_VALUES = ("READY_FOR_REVIEW", "BLOCKED", "FAILED")
MAX_BLOCKS_PER_SESSION = 2


def last_assistant_message(payload: dict) -> str | None:
    """The host-provided last message first (official field), then the transcript."""
    for key in ("last_assistant_message", "lastAssistantMessage"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    transcript = payload.get("transcript_path") or payload.get("transcriptPath")
    if not transcript:
        return None
    try:
        lines = Path(str(transcript)).read_text(encoding="utf-8", errors="replace").splitlines()
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


def parse_sections(block: str) -> dict[str, list[str]]:
    """The block's lines grouped under their section header."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in block.splitlines():
        header = SECTION_HEADER.match(line)
        if header:
            current = header.group(1)
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return sections


def report_defects(text: str) -> list[str]:
    """Missing/invalid pieces of the final report, in contract order."""
    defects: list[str] = []
    blocks = FENCED.findall(text)
    if len(blocks) == 0:
        return ["no ```text fenced block found — the report must be one text code block"]
    if len(blocks) > 1:
        defects.append(f"exactly one ```text block required, found {len(blocks)}")
    block = blocks[-1]
    if not REPORT_HEADER.search(block):
        defects.append("missing header 'GOW3 — ZCODE REPORT'")

    sections = parse_sections(block)
    for section in REQUIRED_SECTIONS:
        if section not in sections:
            defects.append(f"missing section {section}")
    for section, fields in REQUIRED_FIELDS.items():
        lines = sections.get(section, [])
        for field in fields:
            # Horizontal whitespace only after the colon: \s* would swallow the newline
            # and "validate" an empty value against the next line's content.
            if not any(re.match(rf"^\s*{re.escape(field)}:[ \t]*\S", line) for line in lines):
                defects.append(f"missing or empty field {section}.{field}")
    status_lines = [line.strip() for line in sections.get("FINAL STATUS", []) if line.strip()]
    if status_lines and status_lines[0] not in STATUS_VALUES:
        defects.append(f"FINAL STATUS must be one of {', '.join(STATUS_VALUES)}")
    if not any(line.strip() for line in sections.get("RISKS", [])):
        if "RISKS" in sections:
            defects.append("RISKS section is empty (write NONE when there are none)")
    if not any(line.strip() for line in sections.get("NEXT", [])):
        if "NEXT" in sections:
            defects.append("NEXT section is empty")
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
        g.warn(f"already blocked {count} times in this session; passing so the session can"
               " end. The final report is still missing or invalid — fix it in the next"
               " message.")
        return g.PASS

    text = last_assistant_message(payload)
    if text is None:
        g.warn("no readable assistant message; failing open")
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
