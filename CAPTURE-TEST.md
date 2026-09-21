# CAPTURE-TEST

Verification that automatic prompt/response capture is installed and fires on
its own, including in a session that did not install it.

## 1. Tool and model

| | |
|---|---|
| Tool | Claude Code CLI, version `2.1.278` |
| Model | `claude-opus-5` — Opus 5, 1M context, effort `medium` |
| Planner / executor split | None. One model plans and executes in the same turn. |

## 2. Mechanism

Claude Code has a first-class hook system, so nothing needed wrapping. Two
lifecycle events are bound to one script:

| Event | Fires | Supplies |
|---|---|---|
| `UserPromptSubmit` | on every prompt submission | `prompt`, verbatim |
| `Stop` | at end of turn | `last_assistant_message`, `transcript_path` |

**Config file changed:** `.claude/settings.json` (committed, repo root).

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

**Script:** `.claude/hooks/capture.py`, written for this assignment. Claude Code
supplies the event system; the capture logic is not shipped with anything.

Why this captures the prompt and final response and nothing in between: the
`Stop` payload's `last_assistant_message` is *already* only the final text of
the turn. Thinking, tool calls, file reads and diffs never enter the payload,
so excluding them is not filtering the script has to get right. The script
reads the session transcript only to recover responses that span several text
blocks, and to resolve the model name, which no hook payload or environment
variable exposes.

Entries are append-only below an `<!-- ENTRIES BELOW ARE APPEND-ONLY -->` marker.
Only the frontmatter above it is regenerated, because `total_exchanges` and
`last_prompt_time` must stay accurate. Counters live in
`.agent-logs/state/<session-id>.json` rather than being parsed back out of the
log, so captured text can never steer the logger.

## 3. Where the canaries landed

Two canaries, typed by hand, in two different sessions. The hook was installed
from session `3023b1a7`; session `ae6bae58` did not install it and captured
anyway, which is the requirement that matters — a hook that only works in the
session that created it is not installed.

| Canary | Session | Log file |
|---|---|---|
| #1 | `3023b1a7` (installed the hook) | `.agent-logs/2026-09-20_17-50-05_3023b1a7-152f-4e8e-922b-0914095b6b8a.md` |
| #2 | `ae6bae58` (fresh session) | `.agent-logs/2026-09-21_04-58-42_ae6bae58-b630-420c-aa2c-5f34091c2577.md` |

## 4. Canary entries, raw

### Canary #1 — session `3023b1a7`

~~~~~
[LOG_ENTRY type=PROMPT num=11 session=3023b1a7]
timestamp: 2026-09-21T04:41:33.165Z
model: claude-opus-5



<pasted_content id="da42">
CAPTURE TEST — 8x assignment, Ashar
</pasted_content id="da42">

[LOG_ENTRY type=RESPONSE num=11 session=3023b1a7]
timestamp: 2026-09-21T04:47:44.829Z
model: claude-opus-5

Your canary landed as **`PROMPT num=11`**, `2026-09-21T04:41:33.165Z`, `model: claude-opus-5`. Its `RESPONSE` entry gets written when this turn ends — which is why I haven't done the `CAPTURE-TEST.md` reframe yet: the entry I need to paste doesn't exist until after I stop talking.

Meanwhile the canary earned its keep by breaking two things.

**The `<synthetic>` in frontmatter.** Your request arrived as two submissions. `num=9` was superseded and got no response, and Claude Code recorded a `<synthetic>` assistant message for it — its marker for a locally generated message, not a model. So `num=10`'s prompt-time lookup returned `<synthetic>`. Now filtered when asking "which model is serving this session," while a response whose text genuinely *is* synthetic still records it truthfully.

**The one that would have eaten data.** I was deriving counters by scanning the log body — and captured response text can contain lines identical to an entry header. Quoting the log inside a response is enough. A quoted `RESPONSE` header for the number about to be written would satisfy the duplicate check and make a **real response silently never get written**.

This session's entire subject is the log format, so my responses quote entry headers constantly. It was going to fire, probably while writing `CAPTURE-TEST.md`. Counters now live in `.agent-logs/state/<session-id>.json`; the log is append-only output and is no longer parsed for control flow.

A third bug fell out of testing: when the transcript poll timed out, the stale transcript still held the *previous* turn, and its text beat `last_assistant_message` — logging the wrong response against a prompt. The reported text now wins on a mismatch.

Verified against six adversarial cases, including a response body quoting both a same-session prompt header and a same-session response header:

```
frontmatter model : claude-opus-5      (no injected values)
total_exchanges   : 2                  (not inflated)
poison preserved  : True               (captured text still verbatim)
real response written despite poisoned dedup? True
```

Bootstrapped state for this session and cross-checked it: `n_prompts: 11`, `last_response_num: 10` — matching 11 prompt headers and 9 response headers, the gap being `num=9`, your superseded submission. That gap is real and stays.

```
7bcd4c6 Move capture counters out of the log body into a state file
```

**Next message can be anything** — I'll do the `CAPTURE-TEST.md` reframe first thing, with your canary as the primary evidence in `§3`/`§4` and the headless pair demoted to `§5`. Then open the new session, send the canary as its first prompt, and paste the assignment.
~~~~~

### Canary #2 — session `ae6bae58`

~~~~~
[LOG_ENTRY type=PROMPT num=1 session=ae6bae58]
timestamp: 2026-09-21T04:58:42.369Z
model: claude-opus-5



<pasted_content id="0398">
CAPTURE TEST — 8x assignment
</pasted_content id="0398">

, Ashar Khan, second session

[LOG_ENTRY type=RESPONSE num=1 session=ae6bae58]
timestamp: 2026-09-21T04:58:59.412Z
model: claude-opus-5

Capture confirmed. This session's prompt was logged to a fresh file:

`.agent-logs/2026-09-21_04-58-42_ae6bae58...md` — `PROMPT num=1`, timestamp `04:58:42.369Z`, with the pasted block and the trailing `, Ashar Khan, second session` both captured verbatim. Counters live in `.agent-logs/state/ae6bae58-....json`, per the recent refactor.

Two things worth noting:
- Frontmatter `model: unknown` and the entry's `model: unknown-at-prompt-time` — expected, since the prompt hook fires before the model is known. The previous fix covered RESPONSE entries only; the frontmatter should get backfilled once this turn's RESPONSE entry is written.
- The first session's log and state file are still showing as modified in git (uncommitted).

Want me to verify the RESPONSE entry + frontmatter backfill for this turn, or leave it here?
~~~~~

## 5. What did not work

### 5.1 My offline test harness produced invalid JSON

The first end-to-end test wrote one entry with the wrong number and dropped the
rest. The script was fine; the harness was not. I fed payloads in with shell
`echo`, and zsh's `echo` expands `\n`, so the literal newlines in my test
prompt broke the JSON. Every run raised in `json.loads`, hit the catch-all, and
exited 0 silently.

Worth keeping because it proved the right thing by accident: a malformed
payload cannot break a turn. It also showed the cost of that guarantee — a
silent logger failure is invisible, which is why later checks run against real
payloads rather than synthetic ones.

### 5.2 I predicted project hooks would need a restart. They did not.

I told the user the hooks probably would not fire in the session that created
`.claude/settings.json`, assuming Claude Code snapshots hook config at startup.
Wrong: the next prompt in that same session was captured, with no restart and
no approval step.

### 5.3 There is no model environment variable

The model lookup originally tried `CLAUDE_MODEL_ID` and `CLAUDE_MODEL` before
falling back to the transcript. Dumping the hook environment showed neither
exists. Available: `CLAUDE_PROJECT_DIR`, `CLAUDE_CODE_SESSION_ID`,
`CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_EFFORT`, `CLAUDE_PID` and similar — nothing
naming the model. Neither hook payload carries one either. I removed the dead
lookup rather than leave code implying a fallback existed.

### 5.4 `model: unknown` — a race with the transcript write

An early canary captured its prompt and response correctly but recorded
`model: unknown`. The `Stop` hook fires *before* Claude Code finishes writing
the turn to the session `.jsonl`. The script read the transcript immediately,
found nothing, and quietly served the response text from the
`last_assistant_message` fallback — while the model, which had no fallback,
came out empty.

The failure mode is the notable part: the log looked almost right. The response
was complete and correct, so nothing drew attention to the missing model.

Fixed in commit `ab3683f` by `resolve_final()`, which polls the transcript until
the trailing run exists, carries a model, and matches the tail of
`last_assistant_message` — that last condition is what proves the run belongs
to *this* turn and not the previous one. `Stop` runs after the response is
already on screen, so the wait is never user-visible.

### 5.5 Counters derived from the log body could be poisoned by the log itself

The prompt counter and duplicate check were computed by scanning the log body
for entry headers. Captured response text can contain lines identical to a
header — quoting the log inside a response is enough. The consequences were an
inflated exchange count, foreign model names reaching the frontmatter, and
worst, a quoted `RESPONSE` header satisfying the duplicate check so a real
response would never be written at all.

Given that this session's whole subject is the log format, responses here quote
entry headers constantly, so it was going to fire. Fixed in `7bcd4c6` by moving
counters to `.agent-logs/state/<session-id>.json`. The log is append-only
output and is no longer parsed for control flow.

### 5.6 A stale transcript could log the wrong response

Found while testing 5.5. When the transcript poll timed out, the transcript was
still showing the *previous* turn, and its text was preferred over
`last_assistant_message` — attaching the wrong response to a prompt.
`resolve_final()` now reports whether the transcript actually agreed with the
turn; on a mismatch the hook-reported text wins and the stale model is
discarded rather than borrowed.

### 5.7 `<synthetic>` is not a model

Frontmatter briefly read `model: claude-opus-5, <synthetic>`. A prompt had been
superseded, got no response, and Claude Code recorded a `<synthetic>` assistant
message for it — its marker for a locally generated message. The next prompt's
model lookup then returned `<synthetic>`. Now filtered when answering "which
model is serving this session", while a response whose text genuinely came from
a synthetic message still records it truthfully.

### 5.8 `timeout` does not exist on macOS

Minor. `timeout 180 claude -p ...` to bound a headless run; macOS has no
`timeout` binary.

## 6. Known limitations

**The model on a session's first prompt is backfilled, not known live.**
`UserPromptSubmit` fires before any model has run and its payload has no model
field, so the entry is first written with `unknown-at-prompt-time`. At `Stop`
the model is known, and since prompt and response of one turn share it, the
hook replaces that single placeholder in the entry it wrote. The replacement is
targeted by the byte offset recorded at write time, so it cannot touch an
identical-looking header inside captured text, and nothing else in the entry
changes. This is the one case where a written entry is modified; it completes a
field that was unknowable at write time rather than revising anything captured.

**The first message of session `3023b1a7` is not captured.** That session opened
with the capture brief itself, before any hook existed, so its log begins at
`PROMPT num=1`, "So now have you set up the logging already...". The missing
entry has not been hand-written in — a fabricated entry would be worse than a
visible gap.

**`PROMPT num=9` in session `3023b1a7` has no response.** A prompt was submitted
twice; the first was superseded. The gap is real and left in place.

**Session `3023b1a7`'s log is capture-setup conversation, not project work.**
A consequence of one file per session, not a defect — project work starts in a
separate session with its own log.

## 7. Note on removed files

Two earlier canaries were run non-interactively via `claude -p` to test
cross-session firing before the hand-typed ones existed. At the repository
owner's instruction they were deleted, on the grounds that the canary was meant
to be sent by hand. Their content is still reachable in git history at
`7d8b061`, and the bug described in 5.4 was originally found by one of them.
