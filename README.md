# Friday

**Not knowing is the asset.** Friday is a terminal you hand a goal to and watch:
**Claude is the mind, Codex is the hands.** Claude decides everything — what to
do next, whether it's right, when it's done. The builder only executes Claude's
instructions and never decides. You set the goal and watch them work.

The name is the split: **Fri** (Hermès orange) is the fast hand, **Day** (ivory)
is the slow judgment.

## Why this shape

Every other multi-agent tool coordinates interchangeable agents by prompt.
Friday's one rule is different and **enforced by the tools each agent is given**:

> **Claude cannot write. Codex cannot decide.**

Claude runs with read-only tools — it reads to route, and *verifies* (runs
`git diff`, the tests) to ground its judgment while Codex builds, but it physically
cannot edit a file. Codex is the only hand that writes, and it only
ever executes Claude's exact instruction; it never sees the goal and has no
authority over scope. Each agent is deliberately deprived of one power. "Not
knowing is the asset" means the executor is kept from judging its own output, and
the judge is kept from quietly doing the work — so plausible-but-wrong work gets
caught instead of shipped.

## Install

```
pip install .          # registers the `friday` command
```

Friday drives two CLIs — **[Claude Code](https://claude.com/claude-code)** and
**[Codex](https://github.com/openai/codex)** — so both must be installed and
signed in:

```
claude    # log in once
codex     # log in once
```

Running `friday` in a fresh directory sets up a workspace there.

## Use it

```
friday
```

Then just type. Claude routes by its own judgment:

- **A question** ("can you review this code?") → Claude reads the repo and
  answers. No build, no ceremony.
- **A goal** ("add rate limiting to the login API") → Claude writes a first brief
  and the build begins: **Codex builds while Claude watches — at the same time.**

```
────────────────────────────────────────────
  › add rate limiting to the login API

  ● codex
    $ cat src/api/auth.py
    · edit src/middleware/ratelimit.py
    Added ratelimit.py and wired it into auth.py.

  ● claude                        ← ran `git diff`; the diff has no tests
    Codex, add tests/test_ratelimit.py covering the cap and the reset window.

  ● codex
    · edit tests/test_ratelimit.py
    $ python -m pytest -q
      3 passed

  ● claude
    ✓ done                        ← verified: it ran the tests itself
```

Codex works a brief continuously; every ~`review_seconds` and on each concrete
step (a command finishing, a file written) Claude reviews the live stream, checks
it against reality, and returns a verdict — keep going, correct, ask, or done.
Press any key any time to steer (it becomes a correction); answer Claude if it
asks — an empty answer just keeps the build going, it never drops the goal.

## Under the hood

- **Concurrent, to cut a wrong turn early.** Codex never freezes waiting for a
  verdict, and Claude never waits for Codex to finish — the payoff isn't raw speed
  (Codex's build time dominates either way), it's killing a bad direction fast.
- **Claude verifies, never writes.** The overseer runs a fixed, read-only
  allowlist — `git diff`, `git status`, and your `verify_command` (a test runner) —
  to check Codex's claims against ground truth, because a builder's self-report is
  least trustworthy exactly when it fails (says "done" without testing, half-breaks
  a file and only streams "edited X"). It may **verify, never author**.
- **Structured verdicts** (`continue` · `correct` · `ask` · `done`) so dispatch is
  reliable. A *hard* correction kills Codex and respawns it with a folded-in brief;
  a soft one folds into the next brief. A human keypress is just another correction.
- Codex runs each brief in a **fresh session** (`--ephemeral`) so stale context
  never leaks between briefs.

See `docs/pipelining.md` for the design and its trade-offs. `docs/` also keeps the
earlier explorations (an enforced information-asymmetry validation system) as
history — that machinery has been retired in favor of the loop above.

## Develop

```
pip install -e .
PYTHONUTF8=1 python -m pytest -q
```
