- Feature: Have an agent fix the day's most pressing finding, as a pull request for you to review
  The pick is handed to T3 Code in a worktree and branch of its own, with the app project's AGENTS.md.
  Its pull request is checked by master's lint and tests, the outcome written on it, and its finding marked done once you merge it, or set aside if you close it.
  One is fixed at a time; `[improve] runner = ""` keeps the scan and launches no agent.
