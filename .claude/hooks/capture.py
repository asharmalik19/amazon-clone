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
import time

MARKER = "<!-- ENTRIES BELOW ARE APPEND-ONLY -->"

# Matches a full three-line entry header, and captures the session short id so
# entries quoted from *other* sessions inside a captured response cannot be
# mistaken for this session's own entries. Scanning the body loosely is unsafe:
# a response that discusses or pastes log entries contains lines that look
# exactly like headers.
ENTRY_RE = re.compile(
    r"^\[LOG_ENTRY type=(PROMPT|RESPONSE) num=(\d+) session=(\S+?)\]\n"
    r"timestamp: (.+)\n"
    r"model: (.+)$",
    re.M,
)


def is_real_model(name):
    """Claude Code writes `<synthetic>` for locally generated assistant
    messages -- interrupted turns, superseded prompts, API error notices. It is
    a marker, not a model, so it must not be reported as the session's model."""
    return bool(name) and not name.startswith("<") and not name.startswith("unknown")

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
    """Most recent model that actually served a request in this session.

    Skips `<synthetic>` messages so an interrupted or superseded turn does not
    make the following prompt report `model: <synthetic>`.
    """
    for d in reversed(entries):
        if d.get("type") == "assistant":
            model = (d.get("message") or {}).get("model")
            if is_real_model(model):
                return model
    return None


def scan_entries(body, session_short):
    """Entries already written for this session, parsed from strict headers.

    Bootstrap only. Captured response text can contain lines identical to an
    entry header -- quoting the log inside a response is enough -- so this is
    never used for control flow once a state file exists.
    """
    found = []
    for m in ENTRY_RE.finditer(body):
        if m.group(3) == session_short:
            found.append(
                {"type": m.group(1), "num": int(m.group(2)), "model": m.group(5).strip()}
            )
    return found


def state_path(session_id):
    return os.path.join(LOGDIR, "state", "%s.json" % session_id)


def load_state(session_id, body, short):
    """Authoritative counters, kept outside the log.

    Deriving these from the log body is unsafe: a captured response that
    quotes an entry header of this same session would inflate the count, and
    a quoted RESPONSE header could make a real response look already-written
    and be silently dropped. The log is append-only output; this is the input.
    """
    try:
        with open(state_path(session_id), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        pass

    # No state file: seed from the body once. Safe here because a log written
    # before this function existed cannot yet contain quoted headers for
    # entries beyond the ones actually recorded.
    entries = scan_entries(body, short)
    prompts = [e["num"] for e in entries if e["type"] == "PROMPT"]
    responses = [e["num"] for e in entries if e["type"] == "RESPONSE"]
    models = []
    for e in entries:
        if is_real_model(e["model"]) and e["model"] not in models:
            models.append(e["model"])
    return {
        "n_prompts": max(prompts) if prompts else 0,
        "last_response_num": max(responses) if responses else 0,
        "models": models,
    }


def save_state(session_id, state):
    path = state_path(session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


def final_assistant_run(entries):
    """Trailing text run of the turn, and the model that produced it.

    Each content block lands on its own transcript line, so we walk backwards
    collecting `text` blocks and stop at the first thing that marks the end of
    the final run: a tool_use, a tool_result, or a user prompt. `thinking`
    blocks are skipped -- they are deliberately not part of the log.

    Text and model are read from the *same* run so they cannot disagree. Taking
    the model from "latest assistant message anywhere in the transcript"
    instead would return the previous turn's model whenever the current turn
    has not been flushed to disk yet.

    Returns (text, model), either of which may be empty/None.
    """
    chunks = []
    model = None
    for d in reversed(entries):
        kind = d.get("type")
        if kind == "assistant":
            msg = d.get("message") or {}
            content = msg.get("content")
            if isinstance(content, str):
                chunks.append(content)
                model = msg.get("model") or model
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
                model = msg.get("model") or model
        elif kind == "user":
            # Either a tool result or a real prompt -- both end the final run.
            break
    chunks.reverse()
    return "\n\n".join(c for c in chunks if c.strip()).strip(), model


def resolve_final(transcript_path, expected_tail, deadline=4.0, interval=0.15):
    """Wait for the turn to reach the transcript, then read text and model.

    The Stop hook fires before Claude Code has finished writing the turn to
    the session .jsonl. Reading immediately gave a correct-looking response
    (via the last_assistant_message fallback) with `model: unknown` next to
    it. So poll until the trailing run is present, carries a model, and
    matches the tail of last_assistant_message -- that last check is what
    proves we are looking at *this* turn rather than the previous one.

    Bounded, and the Stop hook runs after the response is already on screen,
    so the wait is never user-visible.

    Returns (text, model, matched). `matched` is False when the poll timed out
    without the transcript agreeing with last_assistant_message -- in that case
    the transcript is still showing the *previous* turn, and trusting it would
    log the wrong response against this prompt.
    """
    waited = 0.0
    text, model = final_assistant_run(read_transcript(transcript_path))

    def agrees():
        return bool(text) and bool(model) and (
            not expected_tail or expected_tail in text
        )

    while waited < deadline and not agrees():
        time.sleep(interval)
        waited += interval
        text, model = final_assistant_run(read_transcript(transcript_path))
    return text, model, agrees()


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

    state = load_state(session_id, body, short)
    n_prompts = state["n_prompts"]

    if mode == "prompt":
        text = payload.get("prompt")
        if not text or not text.strip():
            return
        num = n_prompts + 1
        # The model that will serve this turn is not knowable yet. The
        # UserPromptSubmit payload has no model field, and a dump of the hook
        # environment showed no model variable either (CLAUDE_CODE_SESSION_ID,
        # CLAUDE_PROJECT_DIR, CLAUDE_EFFORT are there; nothing for the model).
        # So we record the last model that actually served a request. A
        # mid-session switch shows up on the RESPONSE entry immediately, and on
        # PROMPT entries from the next turn onward.
        model = model_from_transcript(transcript) or "unknown-at-prompt-time"
        body += format_entry("PROMPT", num, short, now, model, text.rstrip())
        state["n_prompts"] = num
        last_time = now
    else:
        if n_prompts == 0:
            return  # hook installed mid-turn; nothing to pair a response with
        num = n_prompts
        if state["last_response_num"] >= num:
            return  # Stop can fire more than once per turn; don't double-write
        reported = (payload.get("last_assistant_message") or "").strip()
        text, model, matched = resolve_final(
            payload.get("transcript_path"), reported[-60:] if reported else ""
        )
        if not matched and reported:
            # Transcript never caught up. Use what the hook itself reported and
            # do not borrow the stale transcript's model alongside it.
            text, model = reported, None
        if not text:
            text = reported or "(no final text response for this turn)"
        model = model or "unknown"
        body += format_entry("RESPONSE", num, short, now, model, text)
        state["last_response_num"] = num
        last_time = None

    if is_real_model(model) and model not in state["models"]:
        state["models"].append(model)
    models = state["models"]

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
    n_exchanges = state["n_prompts"]

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

    # Only after the log write succeeded, so a crash re-does the entry rather
    # than silently skipping it.
    state["first_prompt_time"] = first_time
    save_state(session_id, state)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A logging failure must never break the turn.
        pass
    sys.exit(0)
