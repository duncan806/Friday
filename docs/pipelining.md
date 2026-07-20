# Pipelining: cut the wrong turn early

> Status: design (revised). The current loop is strictly sequential — Claude
> decides → Codex builds a whole brief → Claude decides again. This replaces it
> with a concurrent one whose single purpose is stated below.

## What this is actually for

The naive pitch is "run Codex and Claude at the same time so nobody waits." That
pitch is wrong, and admitting why is the whole design.

The bottleneck is not Claude's thinking time — it is **Codex's building time**.
Removing Claude's idle wait saves seconds; letting Codex build for two minutes in
the wrong direction costs the whole run. So concurrency here buys exactly one
thing, and we name it:

> **Goal: minimize wrong-turn detection latency** — the time between Codex
> starting down a bad path and that path being cut.

Everything below is judged against that number, not against wall-clock speed. The
sequential loop already handles "let the brief finish, then correct." What
concurrency adds is the power to **abort a brief mid-flight** the moment it goes
wrong. That is the only reason to pay for it.

## Roles (and one deliberate revision)

| | Codex — eyes + hands | Claude — mind |
|---|---|---|
| write | yes (workspace-write) | never |
| author | reads source, edits, runs commands | never reads source to think for Codex |
| **verify** | — | **runs a fixed allowlist of verification commands** |
| horizon | works a whole brief, continuously | judges the stream as it flows |
| authority | none — executes, reports | all — continue, correct, stop, ask |

The earlier draft said "Claude cannot even read — pure mind, pure hands." That was
aesthetics, and it was paid for with the supervisor's eyes. See the next section.

## The failure this design must survive: silent corruption

Claude's judgment cannot rest only on Codex's self-report. Codex fails worst at
exactly the moment it cannot report the failure: it says `done` without running
the tests, or half-breaks a file and streams only `edited X`. On the stream that
reads as normal — so **the failure that most needs a supervisor lands precisely in
the supervisor's blind spot.** Stream-only judgment is self-fulfilling: it trusts
the report most when the report is most likely to be a lie.

So the supervisor gets **one independent channel to ground truth**, without ever
gaining the power to write or to author:

- Claude runs a **fixed allowlist of read-only verification commands** —
  `git diff`, `git diff --stat`, `git status`, and the project's test command —
  via `--allowedTools "Bash(git diff:*) Bash(git status:*) Bash(<test cmd>:*)"`.
- It may **verify**, never **author**. It cannot open source to decide *what*
  Codex should build (that would be doing Codex's thinking); it can only check
  *whether* what Codex claims is true against reality.

The line is clean: **Claude may verify, not author.** "Cannot write, cannot
decide scope by reading the code" holds; "must believe whatever Codex says" does
not. This is a conscious trade — independent observation is the essence of
supervision, and we spend the aesthetic of a blind mind to buy it.

## The loop

```
you give a goal
   │
   ▼
Claude writes the first brief for Codex              (1 Claude call)
   │
   ├──────────────────────────────┬──────────────────────────────┐
   ▼ thread A (worker)             ▼ thread B (overseer)          ▼ main
 Codex builds the brief,          wakes on each Codex milestone   render the
 streaming every step             (command done · file written);  stream live;
 (read / edit / command)          timer only as a fallback.       queue a human
 into a shared buffer.            Runs verify commands, judges:    keypress at any
 On crash/timeout it writes        continue / correct / ask /      time — treated
 an explicit error event,          done  (structured verdict).     as a correction.
 never silence.                   │
   │                              │
   └────────── continue / correct(soft|hard) / ask / done ────────┘
```

Three concurrent parts:

- **Worker (thread A)** — one `codex exec` streaming `--json` into a shared,
  lock-guarded buffer. If it dies (timeout, crash, non-zero exit) it appends an
  explicit `worker_error` event to the buffer. **Failure is never translated to
  silence** — the overseer must see it to route around it.
- **Overseer (thread B)** — woken **primarily by Codex milestones**, with a timer
  only as a fallback for a worker gone quiet or spinning. It runs its verification
  commands, then returns a structured verdict. It sees the stream *and* ground
  truth (diff, tests) — never the source as an author would.
- **Main** — renders the live stream and drains a **non-blocking keypress queue**.
  A human keystroke is a correction, dispatched exactly like Claude's `correct`.

## Correction has two costs, so it has two modes

Kill+respawn for every correction is a trap: it makes correction expensive, and
expensive correction doesn't happen. And each respawn re-injects a "here's what
you did so far" summary — who writes that? If a separate summarizer does, the new
Codex is corrected through two layers of lossy compression (stream → summary →
brief) and never learns why its predecessor went where it did.

Both problems dissolve with two moves:

1. **The overseer authors the correction itself.** It has been watching the
   stream the whole time, so the continuation brief is written by the mind that
   saw the work — one compression, not two. There is no separate summarizer, and
   Claude's own prior briefs are **never fed back to it truncated** (the current
   sequential loop's `history[:400]` bug — Claude losing sight of what it told
   Codex — must not be recreated here).

2. **`correct` carries a `hard` flag**, because the two situations have opposite
   economics:
   - **soft correct** (`hard: false`) — the current direction is fine but needs a
     tweak. Let the running brief finish; the correction becomes the *next*
     brief. No kill, no wasted step. This is the common case.
   - **hard correct** (`hard: true`) — the direction is wrong; finishing wastes
     work. Kill the worker now, respawn with the correction brief. Expensive, and
     the *only* thing that justifies the concurrency — reserved for real
     wrong-turns.

Small fixes ("rename that variable") ride soft correct for free; genuine
wrong-turns pay for hard correct and get their latency cut. The overseer picks.

## The verdict

Structured output — dispatch never string-matches Codex's prose (a magic
`startswith("BUILD")` protocol evaporates a real report the day Codex opens a
sentence with "Building…"; control signals come only from Claude's schema):

```
{ verdict: "continue" | "correct" | "ask" | "done",
  hard:    bool,          // only meaningful for "correct"
  note:    string }       // the correction, the question, or why it's done
```

- `continue` — direction good, let it run. No Claude→Codex churn.
- `correct` — inject `note` as a correction; `hard` chooses kill-now vs next-brief.
- `ask` — the overseer is unsure this matches intent. **Surface `note` to the
  human and pause** — do not force a continue/correct guess. "Is this what you
  meant?" is the question a supervisor needs most often, and the earlier
  continue/correct-only vocabulary had no way to raise it.
- `done` — the goal is met, **and verified by Claude's own commands** (tests it
  ran passed, diff matches the goal) — not merely because Codex streamed the word
  "done." The worker stops.

## Interfaces to build

```
providers.codex_run(brief, *, on_event, sandbox="workspace-write", cwd, model,
                    stop: threading.Event) -> str
    # streams codex; stop.set() kills the subprocess (hard correct / done).
    # A crash/timeout surfaces as an on_event({type:"worker_error", ...}), not "".

providers.claude_review(goal, brief, stream_summary, verify, *, timeout) -> dict
    # -> {verdict, hard, note}. Runs claude with a verification-only allowlist:
    #   --allowedTools "Bash(git diff:*) Bash(git status:*) Bash(<test>:*)"
    # `verify` names the project's test command. No write, no source authoring.

tui._pipeline(root, config, goal, stop_fn)
    # worker + overseer threads; milestone-primary review triggers, timer
    # fallback; live render; non-blocking keypress queue -> correction.
```

## What we pay (named on purpose)

- **More Claude calls.** Milestone-triggered review calls Claude more than the
  sequential loop. The dial is trigger granularity, not a blind timer.
- **Hard-correct waste.** Killing mid-brief discards the in-flight step and
  re-spins Codex startup. That is why `correct` defaults to soft; hard is only for
  a wrong direction, where finishing would waste more.
- **A supervisor with hands on verify commands.** Claude now runs commands — a
  real authority grant beyond "read-only mind." We took it deliberately: a blind
  supervisor is a decoration. **Verify, never author** is the wall that keeps the
  grant honest.

## The human

You give the goal and watch. Press a key any time — it queues a correction
(identical to Claude's `correct`), it never blocks the round waiting for you. If
Claude raises `ask`, answer it; **an empty answer means "keep going," it never
discards the goal** (the sequential loop's empty-input-drops-everything bug must
not return). Nothing hides behind a black box: Codex's every step, Claude's every
verify command and verdict, scroll live.

## Bugs in the current sequential loop this design must not inherit

These were found reviewing `tui.py`; the pipeline supersedes most, but each is a
concrete "do not recreate":

1. **Truncated self-history** — Claude's own instruction stored at `[:400]`, so
   next round it misreads what it ordered. → Overseer holds its own understanding;
   never re-feed Claude a truncated version of its own words.
2. **Blocking steer window** (`_steer_window(1.4)`) — too short to decide, wasted
   when unused. → Non-blocking keypress queue drained by main; `_key()` is already
   non-blocking.
3. **Empty `ask` answer discards the goal.** → Empty = continue.
4. **Codex failure → `""` → `"(no report)"`** — a crash reads as silence and
   Claude instructs on. → Explicit `worker_error` in the stream.
5. **String-prefix control protocol** (`startswith(("ESCALATE","BUILD"))`) — a
   normal report starting with "Building…" vanishes. → Structured verdict only;
   Codex prose is rendered, never parsed for control.
6. **180s auth probe** — a boot check waiting three minutes. → 15–30s is enough
   for `auth status`.

## Implementation plan

1. `codex_run` with a `stop` event and an explicit `worker_error` event on death;
   lock-guarded buffer.
2. `claude_review` — verification-only allowlist, structured `{verdict, hard,
   note}`.
3. `_pipeline` — worker + overseer threads, milestone-primary triggers with timer
   fallback, live render, non-blocking keypress → correction.
4. Swap `_run_goal` → `_pipeline`; give Claude the verify allowlist, not source
   reads.
5. End-to-end on a real goal, deliberately including a silent-corruption case
   (Codex says done without tests) to prove the verify channel catches it.
