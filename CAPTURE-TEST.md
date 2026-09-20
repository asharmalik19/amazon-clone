# CAPTURE-TEST

Verification that automatic prompt/response capture is installed and fires on
its own, including in sessions that did not install it.

## 1. Tool and model

| | |
|---|---|
| Tool | Claude Code CLI, version `2.1.278` |
| Model (interactive session) | `claude-opus-5` — Opus 5, 1M context, effort `medium` |
| Model (headless `claude -p` sessions) | `claude-sonnet-5` |
| Planner / executor split | None. One model plans and executes in the same turn. |

There is no separate planning model. The model difference above is not a
deliberate division of labour — it is the local configuration: `~/.claude/settings.json`
requests `opus[1m]`, while managed settings pin `Sonnet 5` for newly started
sessions. Both models therefore appear in the logs, which is the case the
brief's "so a switch mid-build is visible" requirement exists for.

## 2. Mechanism

Claude Code has a first-class hook system, so nothing needed wrapping. Two
lifecycle events are wired to one script:

| Event | Fires | Gives us |
|---|---|---|
| `UserPromptSubmit` | on every prompt submission | `prompt`, verbatim |
| `Stop` | at end of turn | `last_assistant_message`, `transcript_path` |

**Config file changed:** `.claude/settings.json` (committed, in the repo root).

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "timeout": 15,
                    "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/capture.py\" prompt" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "timeout": 15,
                    "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/capture.py\" response" }] }
    ]
  }
}
```

**Script:** `.claude/hooks/capture.py` (written for this assignment; Claude Code
supplies the event system, not the capture logic).

Why this satisfies "prompt and final response, nothing in between": the `Stop`
payload's `last_assistant_message` is *already* only the final text of the
turn. Excluding thinking, tool calls, file reads and diffs is not filtering the
script has to get right — those never enter the payload. The script reads the
transcript only to recover the trailing text run for turns whose final response
spans several text blocks (`last_assistant_message` holds just the last one)
and to resolve the model name, which no hook payload or environment variable
exposes.

Entries are append-only below an `<!-- ENTRIES BELOW ARE APPEND-ONLY -->`
marker. Only the frontmatter block above it is regenerated, because
`total_exchanges` and `last_prompt_time` have to stay accurate. No captured
entry is ever edited. This is the one place I interpreted the brief's "do not
edit, tidy, summarise, or delete an entry" rule: I read it as governing
entries, not running counters.

## 3. Where the canaries landed

Two canaries, two separate sessions, neither of which installed the hook. The
hook was installed from session `3023b1a7`.

| Canary | Session | Log file |
|---|---|---|
| #1 | `12101aba` | `.agent-logs/2026-09-20_20-38-09_12101aba-dbcc-4b11-a8ba-73565fab9bcd.md` |
| #2 | `9b33059c` | `.agent-logs/2026-09-20_20-44-53_9b33059c-e9dd-4358-8c03-e960b063dad3.md` |

Canary #1 caught a real bug (see §5.4). It is left exactly as captured rather
than re-run in place. Canary #2 is the same canary after the fix.

## 4. Canary entries, raw

### Canary #1 — session `12101aba`, with the `model: unknown` bug

```
[LOG_ENTRY type=PROMPT num=1 session=12101aba]
timestamp: 2026-09-20T20:38:09.225Z
model: unknown-at-prompt-time

CAPTURE TEST — 8x assignment, Ashar


[LOG_ENTRY type=RESPONSE num=1 session=12101aba]
timestamp: 2026-09-20T20:38:13.421Z
model: unknown

This appears to be a test message ("CAPTURE TEST — 8x assignment, Ashar") rather than an actual task request.

I noticed the git status shows recent commits about "automatic prompt/response capture hooks" — it looks like you're testing whether that hook setup is working. Let me know what you'd like me to do next (e.g., verify a specific capture, check the log file, or continue on the assignment itself).
```

### Canary #2 — session `9b33059c`, after the fix

```
[LOG_ENTRY type=PROMPT num=1 session=9b33059c]
timestamp: 2026-09-20T20:44:53.701Z
model: unknown-at-prompt-time

CAPTURE TEST — 8x assignment, Ashar


[LOG_ENTRY type=RESPONSE num=1 session=9b33059c]
timestamp: 2026-09-20T20:44:58.276Z
model: claude-sonnet-5

Got it — this looks like a test message to confirm the capture hooks are firing, not an actual task request. No action needed from me unless you want something done with the `.agent-logs` or `capture.py` changes.
```

## 5. What did not work

### 5.1 My offline test harness produced invalid JSON

First end-to-end test of the script wrote a single entry with the wrong number
and dropped the rest. The script was fine; the harness was not. I fed payloads
in with shell `echo`, and zsh's `echo` expands `\n`, so the literal newlines I
put in the prompt string broke the JSON. Every run raised on `json.loads`, hit
the catch-all, and exited 0 silently.

Worth keeping because it accidentally proved the right thing: a malformed
payload cannot break a turn. It also showed the cost of that guarantee — a
silent logger failure is invisible, which is why the canary is run against real
payloads rather than synthetic ones.

### 5.2 I predicted project hooks would need a restart. They did not.

I told the user the hooks probably would not fire in the session that created
`.claude/settings.json`, on the assumption that Claude Code snapshots hook
config at startup. Wrong: the next prompt in that same session was captured
with no restart and no `/hooks` approval step.

### 5.3 There is no model environment variable

I first wrote the model lookup to try `CLAUDE_MODEL_ID` and `CLAUDE_MODEL`
before falling back to the transcript. Dumping the hook environment showed
neither exists. Available: `CLAUDE_PROJECT_DIR`, `CLAUDE_CODE_SESSION_ID`,
`CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_EFFORT`, `CLAUDE_PID` and similar — nothing
naming the model. The `UserPromptSubmit` and `Stop` payloads have no model
field either. Removed the dead lookup rather than leave code implying a
fallback existed.

### 5.4 `model: unknown` — a race with the transcript write

Canary #1 captured prompt and response correctly but recorded
`model: unknown`. The `Stop` hook fires *before* Claude Code finishes writing
the turn to the session `.jsonl`. The script read the transcript immediately,
found nothing, and quietly served the response text from the
`last_assistant_message` fallback — while the model, which had no fallback,
came out empty.

The failure mode is worth noting: the log looked almost right. The response was
complete and correct, so nothing drew attention to the missing model except
reading the file.

It also mattered more than it appeared. That session ran `claude-sonnet-5`
while the interactive session ran `claude-opus-5`, so the logger was dropping
precisely the model switch the format is designed to expose.

Fixed by `resolve_final()`, which polls the transcript for up to 4s until the
trailing run exists, carries a model, and matches the tail of
`last_assistant_message` — that last condition is what proves the run belongs
to *this* turn rather than the previous one. `final_assistant_run()` now returns
text and model from the same run so they cannot disagree; the earlier helper
took the newest model anywhere in the file, which would have reported a stale
model on any unflushed turn. `Stop` runs after the response is already on
screen, so the wait is never user-visible.

### 5.5 `timeout` does not exist on macOS

Minor. Used `timeout 180 claude -p ...` to bound the headless canary; macOS has
no `timeout` binary. Dropped it and used the tool's own timeout.

## 6. Known limitations, not worked around

**The first prompt of every session records `model: unknown-at-prompt-time`.**
At `UserPromptSubmit` no model has served a request yet, and the payload has no
model field, so the value is genuinely unknowable at write time. The `RESPONSE`
entry of the same turn carries the authoritative model, so no information is
lost. On later turns the `PROMPT` entry shows the last model that actually
served a request, which means a mid-session switch appears immediately on
`RESPONSE` entries and one turn later on `PROMPT` entries.

I could backfill the `PROMPT` model at `Stop` time, and chose not to: it would
mean rewriting an entry after the fact, and an honest placeholder is worth more
than a tidier log.

**The first message of session `3023b1a7` is not captured.** That session
opened with the capture brief itself, before any hook existed, so the log
begins at `PROMPT num=1`, "So now have you set up the logging already...". I
have not hand-written the missing entry in. A fabricated entry would be worse
than a visible gap.

**The installing session's log contains capture-setup conversation, not project
work.** That is a consequence of one file per session, not a defect: project
work starts in a new session and gets its own clean log file.
