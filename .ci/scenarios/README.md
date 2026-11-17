# Scenario switches

A file here turns on extra CI jobs for one branch's PR runs. Its path is the
branch name: `scn/manual-k3x9ab` reads `.ci/scenarios/scn/manual-k3x9ab`.
Each keyword on its own line:

```
slow 45   # sleeps 45 minutes (default 10)
manual    # deploys a preview that waits on the "preview" environment
stuck     # waits for a self-hosted runner that does not exist
flaky     # fails with a network error on the first attempt, passes on a re-run
```

Runs on main never read these files, so a merged one does nothing.
`bin/scenario cleanup --prune` removes them.
