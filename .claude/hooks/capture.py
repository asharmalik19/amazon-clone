#!/usr/bin/env python3
"""Append-only prompt/response capture for Claude Code.

Wired up in .claude/settings.json as two hooks:

    UserPromptSubmit -> capture.py prompt     (writes the verbatim prompt)
    Stop             -> capture.py response   (writes the final assistant text)

Both events hand us a JSON payload on stdin. UserPromptSubmit carries the
prompt verbatim; Stop carries `last_assistant_message`, which is already just
the final text of the turn -- no thinking, no tool calls, no intermediate
steps. That is exactly the slice we want, so most of the work here is
bookkeeping rather than extraction.

Design rules, in priority order:

1. Never fail a turn. Any exception exits 0 and stays silent. A broken logger
   must not become a broken session.
2. Entries are append-only. The frontmatter/header block above the MARKER is
   regenerated on every write (it holds running counters that have to stay
   accurate); everything below the MARKER is only ever appended to.
3. The prompt is written the moment it is submitted, not at end of turn. If a
   turn is interrupted or crashes, the prompt still lands and the log honestly
   shows a prompt with no response.
"""

import datetime
import glob
import json
import os
import re
import sys

MARKER = "<!-- ENTRIES BELOW ARE APPEND-ONLY -->"

# capture.py -> hooks -> .claude -> repo root. Derived from __file__ rather
# than $CLAUDE_PROJECT_DIR so the script works regardless of how it is invoked.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGDIR = os.path.join(REPO, ".agent-logs")


def utc_now():
    d = datetime.datetime.now(datetime.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def load_config():
    cfg = {
        "author": "UNSET-github-handle",
        "project": os.path.basename(REPO),
        "tool": "claude-code",
    }
    path = os.path.join(LOGDIR, "config.env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                cfg[k.strip().lower()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return cfg


def read_transcript(path):
    """Load the session .jsonl. Returns [] on any problem -- callers degrade."""
    if not path:
        return []
    out = []
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out


def model_from_transcript(entries):
    """Most recent model that actually served a request in this session."""
    for d in reversed(entries):
        if d.get("type") == "assistant":
            model = (d.get("message") or {}).get("model")
            if model:
                return model
    return None


def final_assistant_text(entries):
    """Reconstruct the trailing text run of the turn from the transcript.

    Each content block lands on its own transcript line, so we walk backwards
    collecting `text` blocks and stop at the first thing that marks the end of
    the final run: a tool_use, a tool_result, or a user prompt. `thinking`
    blocks are skipped -- they are deliberately not part of the log.

    Used as a fallback, and to catch turns whose final response spans several
    text blocks (where `last_assistant_message` only holds the last one).
    """
    chunks = []
    for d in reversed(entries):
        kind = d.get("type")
        if kind == "assistant":
            content = (d.get("message") or {}).get("content")
            if isinstance(content, str):
                chunks.append(content)
                continue
            if not isinstance(content, list):
                continue
            parts = []
            saw_tool_use = False
            for block in content:
                btype = block.get("type")
                if btype == "text":
                    parts.append(block.get("text") or "")
                elif btype == "tool_use":
                    saw_tool_use = True
            if saw_tool_use:
                break
            if parts:
                chunks.append("\n".join(parts))
        elif kind == "user":
            # Either a tool result or a real prompt -- both end the final run.
            break
    chunks.reverse()
    return "\n\n".join(c for c in chunks if c.strip()).strip()


def log_path(session_id):
    """One file per session, name fixed at session start and never changed."""
    existing = sorted(glob.glob(os.path.join(LOGDIR, "*_%s.md" % session_id)))
    if existing:
        return existing[0]
    d = datetime.datetime.now(datetime.timezone.utc)
    return os.path.join(
        LOGDIR, "%s_%s.md" % (d.strftime("%Y-%m-%d_%H-%M-%S"), session_id)
    )


def split_existing(path):
    """Return (header, body). body is the append-only region."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None, ""
    if MARKER in text:
        head, body = text.split(MARKER, 1)
        return head, body.lstrip("\n")
    return None, text


def build_header(session_id, cfg, first_time, last_time, models, n_exchanges, date):
    short = session_id[:8]
    lines = [
        "---",
        "session_id: %s" % session_id,
        "date: %s" % date,
        "author: %s" % cfg["author"],
        "model: %s" % (", ".join(models) if models else "unknown"),
        "tool: %s" % cfg["tool"],
        "project: %s" % cfg["project"],
        "total_exchanges: %d" % n_exchanges,
        "first_prompt_time: %s" % first_time,
        "last_prompt_time: %s" % last_time,
        "---",
        "",
        "# Session Log - %s" % date,
        "",
        "Session: `%s` | Project: `%s` | Author: `%s`"
        % (short, cfg["project"], cfg["author"]),
        "",
        "---",
        "",
        MARKER,
        "",
    ]
    return "\n".join(lines) + "\n"


def format_entry(etype, num, short, timestamp, model, text):
    return (
        "[LOG_ENTRY type=%s num=%d session=%s]\n"
        "timestamp: %s\n"
        "model: %s\n"
        "\n"
        "%s\n"
        "\n\n" % (etype, num, short, timestamp, model, text)
    )


def debug_dump(mode, payload):
    """Opt-in payload dump, used while developing the hook. Off by default."""
    target = os.environ.get("CAPTURE_DEBUG_DIR")
    if not target:
        return
    try:
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, "payloads.jsonl"), "a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "mode": mode,
                        "at": utc_now(),
                        "payload": payload,
                        "env": {
                            k: v
                            for k, v in os.environ.items()
                            if "CLAUDE" in k.upper() or "MODEL" in k.upper()
                        },
                    }
                )
                + "\n"
            )
    except OSError:
        pass


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in ("prompt", "response"):
        return

    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    debug_dump(mode, payload)

    session_id = payload.get("session_id") or "unknown-session"
    short = session_id[:8]
    transcript = read_transcript(payload.get("transcript_path"))
    cfg = load_config()
    now = utc_now()

    os.makedirs(LOGDIR, exist_ok=True)
    path = log_path(session_id)
    head, body = split_existing(path)

    prompt_nums = re.findall(r"^\[LOG_ENTRY type=PROMPT num=(\d+) ", body, re.M)
    n_prompts = len(prompt_nums)

    if mode == "prompt":
        text = payload.get("prompt")
        if not text or not text.strip():
            return
        num = n_prompts + 1
        # The model that will serve this turn is not knowable yet, so we record
        # the last one that actually served a request. A mid-session switch
        # shows up on the RESPONSE entry immediately and on PROMPT entries from
        # the next turn on.
        model = (
            os.environ.get("CLAUDE_MODEL_ID")
            or os.environ.get("CLAUDE_MODEL")
            or model_from_transcript(transcript)
            or "unknown-at-prompt-time"
        )
        body += format_entry("PROMPT", num, short, now, model, text.rstrip())
        last_time = now
    else:
        if n_prompts == 0:
            return  # hook installed mid-turn; nothing to pair a response with
        num = n_prompts
        if "[LOG_ENTRY type=RESPONSE num=%d " % num in body:
            return  # Stop can fire more than once per turn; don't double-write
        text = final_assistant_text(transcript)
        if not text:
            text = (payload.get("last_assistant_message") or "").strip()
        if not text:
            text = "(no final text response for this turn)"
        model = model_from_transcript(transcript) or "unknown"
        body += format_entry("RESPONSE", num, short, now, model, text)
        last_time = None

    # Rebuild the header from the body so the counters stay truthful even if a
    # previous run died halfway.
    models = []
    for m in re.findall(r"^model: (.+)$", body, re.M):
        m = m.strip()
        if m and m not in models and not m.startswith("unknown"):
            models.append(m)

    first_time = now
    prev_last = now
    prev_date = None
    if head:
        found = re.search(r"^first_prompt_time: (.+)$", head, re.M)
        if found:
            first_time = found.group(1).strip()
        found = re.search(r"^last_prompt_time: (.+)$", head, re.M)
        if found:
            prev_last = found.group(1).strip()
        found = re.search(r"^date: (.+)$", head, re.M)
        if found:
            prev_date = found.group(1).strip()

    last_time = last_time or prev_last
    date = prev_date or first_time[:10]
    n_exchanges = len(
        re.findall(r"^\[LOG_ENTRY type=PROMPT num=(\d+) ", body, re.M)
    )

    content = (
        build_header(
            session_id, cfg, first_time, last_time, models, n_exchanges, date
        )
        + body
    )
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A logging failure must never break the turn.
        pass
    sys.exit(0)
