# muto

**Not knowing is the asset.** muto is a validation system in which two AI
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

## Running

```
./setup.sh                 # check CLI installation and auth (muto.bat on Windows)
$EDITOR task/task.md       # write the task (read-only once the cycle starts)
python3 orchestrator.py    # start the round loop
open dashboard/index.html  # DOS-style dashboard
```

## Scope

Apply muto to tasks with a clear surface (a CLI interface, etc.), observable
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
