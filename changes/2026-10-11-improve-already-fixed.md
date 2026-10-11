- Fix: A finding master fixed already is marked done, instead of being handed to agent after agent and then set aside
  An agent given an error that an update fixed since (logged by an older version) had no way to say so: its run ended with no pull request, so the finding went to another agent, then was set aside as if you had turned it down.
  The agent now names the commit on master that fixed it; once that commit is checked to be on master the finding is done, and it opens again should the error come back.
