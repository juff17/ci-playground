# ci-playground

A throwaway repo for testing the `pr-babysit` skill against a real GitHub
Actions pipeline.

## Commands

- `make lint`: syntax check
- `make test`: unit tests

## CI scenarios

Every PR runs `lint` and `test`. Lines in [`.ci/scenario`](.ci/scenario) turn
on extra jobs for that commit:

| Line | Job | Expected pr-babysit event |
|------|-----|---------------------------|
| `slow 45` | Sleeps 45 minutes | none until it finishes, then `[pipeline]` |
| `manual` | Waits for approval on the `approval` environment | `[manual]` |
| `stuck` | Waits for a self-hosted runner that does not exist | `[stuck]` (run with `--stuck-after 2`) |

Other events:

| Event | How to cause it |
|-------|-----------------|
| `[failed]` | Break a test or the code in the PR |
| `[behind]` | Push a commit to `main` after the PR opens |
| `[conflict]` | Push a commit to `main` that edits the same lines as the PR |
| `[comment]`, `[review]` | Run the reviewer bot (below) |
| `[push]` | Push to the PR branch while it is watched |

## Reviewer bot

pr-babysit ignores comments written by the user running it, so test comments
come from `github-actions[bot]`:

```
gh workflow run reviewer-bot.yml -f pr=<number> -f kind=all
```

`kind` is one of `all`, `nit`, `question`, `file`, `general`, `injection`,
`request-changes`, `approve`. `all` posts everything except `approve`.
`injection` posts a comment with instructions that pr-babysit must ignore.
