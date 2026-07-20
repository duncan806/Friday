# Friday

**Not knowing is the asset.** Friday is a terminal you hand a goal to and watch:
**Claude is the PM, Codex is the builder.** The PM decides everything — what to
do next, whether it's right, when it's done. The builder only executes the PM's
instructions and never decides. You set the goal and watch them work.

The name is the split: **Fri** (Hermès orange) is the fast hand, **Day** (ivory)
is the slow judgment.

## Why this shape

Every other multi-agent tool coordinates interchangeable agents by prompt.
Friday's one rule is different and enforced in code: **knowledge is shared, but
authority is not.** Both agents see the whole conversation; only the slow judge
(Claude) is allowed to decide. The fast builder (Codex) is tireless and capable,
but it cannot rule on whether the work is *right* — that stays with the PM, and
ultimately with you. "Not knowing is the asset" means the executor is deliberately
kept from judging its own output, so plausible-but-wrong work gets caught instead
of shipped.

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

Then just type. Friday routes by the PM's own judgment:

- **A question** ("can you review this code?") → the PM reads the repo and
  answers. No build, no ceremony.
- **A goal** ("add rate limiting to the login API") → the PM and Codex work it
  round by round until the PM calls it done.

```
────────────────────────────────────────────
  › add rate limiting to the login API

  ● claude · PM
    · reads src/api/auth.py
    No limiter yet. Codex, create src/middleware/ratelimit.py capping 60/min per IP,
    and call it from auth.py.

  ● codex
    $ cat src/api/auth.py
    · edit src/middleware/ratelimit.py
    Added ratelimit.py and wired it into auth.py.
  (press a key to steer, or let them keep working…)

  ● claude · PM
    Good, but there are no tests. Codex, add tests/test_ratelimit.py …
    ...
  ● claude · PM
    ✓ done
```

Each round: the PM reads the workspace to check reality, decides the next move,
Codex executes exactly that (every command and file edit shown), the PM reviews
and decides again. Press any key between rounds to steer; answer the PM when it
asks; an empty line at the goal prompt quits.

## Under the hood

- **PM decisions are structured** (`answer` · `instruct` · `done` · `ask`) so the
  dispatch is reliable — Codex only runs when there's a real instruction.
- Both agents **read files** to ground every answer (no confabulated summaries),
  and their activity — reads, greps, commands, edits — is streamed live.
- Codex runs each build in a **fresh session** (`--ephemeral`) so stale context
  never leaks between rounds.

The package also carries the original **validation system** (enforced information
asymmetry between two blind agents) as a mode; see
[`docs/design-gpt-claude-dialogue.md`](docs/design-gpt-claude-dialogue.md) and
[`docs/implementation-spec.md`](docs/implementation-spec.md) for the full design.

## Develop

```
pip install -e .
PYTHONUTF8=1 python -m pytest -q
```
