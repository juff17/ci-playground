# ci-playground

A repo for testing minion-hub's monitors (`pr-babysit`, `pipeline-watch`, and
the Monitors and Pipelines views) against real GitHub Actions pipelines.

Scenario PRs really get merged, so the repo is laid out to keep `main` green
whatever they do.

## Layout

| Path | What it is | Scenario PRs |
|------|------------|--------------|
| `calc/`, `tests/` | The "product" and its tests | never touch it |
| `sandbox/` | Code that scenario PRs add, one `scn_<id>.py` and its test each | add files here, safe to merge |
| `sandbox/hotspot.txt` | 24 slots that conflict scenarios claim and edit | one slot per conflict PR |
| `sandbox/heartbeat.txt` | Rewritten each time main moves ahead | never touched by PRs |
| `.ci/scenarios/<branch>` | Switches for one branch's PR runs | ignored on main |
| `tools/scenario.py`, `bin/scenario` | Opens scenario PRs, moves main, starts release runs | |

Why `main` stays green:

- Switches are read from a file named after the PR's branch, and only on PR
  runs. A merged switches file does nothing.
- Broken code only goes into `sandbox/`, with the test that catches it.
  `bin/scenario merge` and the main-moving commands merge only when every check
  passed.
- `sandbox/test_hotspot.py` fails on a half-resolved conflict (markers left
  in, or a slot lost), so a bad rebase can't reach main either.
- `bin/scenario cleanup --prune` removes merged scenario files and frees every
  slot, through a PR like any other.

## Commands

- `make lint`: syntax check
- `make test`: unit tests, then the sandbox's tests
- `bin/scenario --help`: scenario tooling (needs `gh` signed in)

Run `bin/scenario setup` once to create the environments: `staging` (no
gate), and `approval` and `production`, which wait for you.

## Pipelines

**CI** (`ci.yml`) runs on every PR. Jobs are named `<stage> / <job>`, so
the monitors show three stages: `setup / scenario`, then `check / lint` and
`check / test`, then any `extra / *` job a switch turns on.

| Switch | Job | Expected event |
|--------|-----|----------------|
| `slow 45` | `extra / slow` sleeps 45 minutes | none until it finishes, then `[pipeline]` |
| `manual` | `extra / approval` waits on the `approval` environment | `[manual]` |
| `stuck` | `extra / stuck` waits for a self-hosted runner that does not exist | `[stuck]` (watch with `--stuck-after 2`) |
| `flaky` | `extra / flaky` fails with a network error on its first attempt, passes on a re-run | `[failed]`, then a proposed retry |

**Release** (`release.yml`) runs on every push to main: `build / package`,
`test / unit`, `deploy / staging`, then `deploy / production`, which waits for
approval on the `production` environment. The deploys only print. One
production deploy runs at a time: a newer run queues behind the one at the
gate, and a newer one still replaces the queued one.

## Scenario PRs

`bin/scenario new KIND` opens a PR from the latest main. `fleet` opens one of
each at once, for testing many monitors side by side.

| Kind | What the PR does | What the monitor should do |
|------|------------------|----------------------------|
| `happy` | adds a helper and its passing test | stage lines, `[pipeline]` passed, `[merged]` after `bin/scenario merge N` |
| `failing` | adds a helper with an off-by-one bug its test catches | `[failed]` on `check / test`, then commit a fix |
| `flaky` | `happy` plus the `flaky` switch | `[failed]` on `extra / flaky`, then propose a retry |
| `manual` | `happy` plus the `manual` switch | `[manual]` on `extra / approval` |
| `slow` | `happy` plus `slow N` (`--minutes N`) | quiet until `[pipeline]` |
| `stuck` | `happy` plus the `stuck` switch | `[stuck]` |
| `behind` | `happy`; then `bin/scenario advance` moves main | `[behind]`, then a clean rebase |
| `conflict` | claims a hotspot slot; then `bin/scenario collide N` edits it on main | `[conflict]`, then resolve `sandbox/hotspot.txt` |
| `comments` | adds a helper with a typo; then `bin/scenario review N` | `[comment]` and `[review]`, then fix the nit and answer |
| `messy` | the bug plus `flaky` and `manual` | `[failed]` twice and `[manual]` on one PR |

`--now` does the follow-up step (move main, collide, post the review) right
away. Without it the script prints the command, so you can attach the
monitor first and watch the event arrive.

Other commands:

| Command | What it does |
|---------|--------------|
| `bin/scenario advance` | Moves main ahead with no conflicts, through a bump PR it merges once green |
| `bin/scenario collide N` | Edits PR N's hotspot slot on main, so PR N conflicts |
| `bin/scenario review N [KIND]` | The reviewer bot comments on PR N (below) |
| `bin/scenario merge N` | Squash-merges PR N, only if every check passed |
| `bin/scenario list` | Open scenario and bump PRs |
| `bin/scenario cleanup [--prune]` | Closes scenario PRs and deletes their branches; `--prune` also clears merged files from main |

Anything that merges takes `--quiet`, which adds `[skip ci]` to the merge
commit so main's Release run doesn't start.

## Release runs for pipeline-watch

`bin/scenario pipeline KIND` starts a Release run on main without changing
code, and prints the `/pipeline-watch` command for it.

| Kind | Run | Expected events |
|------|-----|-----------------|
| `happy` | no gate | every stage passes, `[pipeline]` passed |
| `gated` | the production gate | `[manual]` on `deploy / production` |
| `failing` | `test / unit` fails | `[failed]`, `[pipeline]` failed |
| `late-fail` | gated, then production fails once approved | `[manual]`, then `[failed]` |
| `flaky` | `deploy / staging` fails on its first attempt | `[failed]`, passes on a re-run |
| `slow` | staging takes `--minutes N` | a long `deploy / staging` |

## A full test run

1. `bin/scenario fleet --add slow stuck` opens ten PRs and prints each one's
   expected events.
2. Attach a `/pr-babysit <url>` to each from the Agents hub, and
   `/pipeline-watch` to a `bin/scenario pipeline gated` run.
3. Trigger the follow-ups the fleet printed: `advance`, `collide N`,
   `review N`.
4. Check each monitor against the tables above: the events, the tray notes,
   the approvals it proposes, and the rows in Monitors and Pipelines.
5. Merge the green ones with `bin/scenario merge N`, and watch main's Release
   runs queue at the production gate.
6. `bin/scenario cleanup --prune` when done.

## Reviewer bot

pr-babysit ignores comments written by the user running it, so test comments
come from `github-actions[bot]`:

```
bin/scenario review <number> [kind]
# or: gh workflow run reviewer-bot.yml -f pr=<number> -f kind=all
```

`kind` is one of `all`, `nit`, `question`, `file`, `general`, `injection`,
`request-changes`, `approve`. `all` posts everything except `approve`.
`injection` posts a comment with instructions that pr-babysit must ignore.
