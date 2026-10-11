# {title}

The app's daily improvement scan picked this on {today} ({kind}, `{fingerprint}`): {seen}.

## What shows it

{evidence}
{live_log}
## What to do

{ask}

- Read README.md and SPEC.md first: how the app is built, and its standing preferences.
- Reproduce it before fixing it, as close to how Oscar meets it as you can, so the fix is for the real problem.
- Fix the cause, and add a test that fails without the fix.
- Never touch the live app's data (`%LOCALAPPDATA%\Personal Calendar`); a run from the repo has its own.
- Record the change in `changes/` (README.md, Recording a change).
- Pass the gate: `uv run python -m improve.check`.
- Open a pull request against master with `Improves: {fingerprint}` in its description.

It may be fixed on master already: what shows it can be older than master (an error logged by a version since updated).
Then, once you have shown it is, open no pull request: write `improve-outcome.md` at the root of the worktree you work in, its first line `Already fixed by <commit>` (the commit on master that fixed it), then how you know.
