# friday

**Not knowing is the asset.** friday is a validation system in which two AI
agents—one holding only the Why, the other only the How—converge on software
while communicating through a single channel: blockage reports.
The conventional loop measures "did we build it right" (verification);
this system measures "did we build the right thing" (validation).

- Claude (user role) holds only the task (Why) and cannot see the code—its
  entire world is `workspace/surface/`.
- Codex (builder role) holds only the code (How) and cannot see the task—its
  only input is `reports/`.
- This deprivation is enforced physically by the filesystem, not requested by
  prompt (the two asserts in `integrity.py` are the entirety of system
  reliability).

## Install

```
pip install .              # registers the `friday` command
```

Code lives in site-packages; cycle data lives wherever you run `friday init`.

## Running

Run `friday`. It opens a CRT-inspired ASCII interface and creates a deterministic
workspace when needed. There are no commands to memorize: describe the desired
outcome naturally and friday plants the task and starts the unattended cycle.
Natural-language requests can also add data, inspect or stop a cycle, connect
GitHub/Claude/Codex, and create pull requests. Codex handles control-plane
intent routing with Claude Code as an isolated fallback.

Automation-compatible exceptions are `friday run` (detached by default),
`friday run --attach` (foreground), and `friday status` (one-line summary from
`status.json`). A stopped or crashed cycle resumes after its last completed
round when `friday run` is issued again.

`friday init` turns `workspace/` into a git repo (git must be installed).
Codex requires a repo to run, and the round loop commits `workspace/` after
every Codex turn (`friday: round N`), so the human can observe Codex-side
change history as per-round diffs (spec §7).

## Scope

Apply friday to tasks with a clear surface (a CLI interface, etc.), observable
blockages, and a short build cycle. **Tasks with a thin surface (pure
algorithms, libraries) are out of scope.**

## Open problems (these are part of the spec—do not delete)

U1. Accuracy of the filter's intent-leak judgment—only observable through
auditing the dropped log.
U2. Claude may perform the prediction ritual without committing to it—an area
filesystem enforcement cannot reach; residual risk remains at the prompt layer.
U3. Judging the judgment of inevitability—terminates at the human, and this is
not a defect but the system's honest declaration of its boundary. Accumulating
the verdicts/ casebook is the only path of improvement.
U4. The user role needs Bash to actually use the product, so its file tools
(Edit/Write/Read/Glob/Grep) are blocked but Bash is not. Since workspace/src
and workspace/surface are siblings, a determined `cat ../src/...` from Bash can
still read source. The structural isolation asserts (run before and after each
turn) catch symlink bridges and src relocation, not raw relative-path reads.
Full prevention needs process-level sandboxing; until then this is a known,
observable residual—not hidden.
