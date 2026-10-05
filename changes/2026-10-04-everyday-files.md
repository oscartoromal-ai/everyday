- Major: Keep each project's context as files in the everyday files, the folder for agentic work
  Setup makes `C:\everyday-files` (or the folder chosen on its new Everyday files page) with `repos/`, `projects/` and `work/` in it.
  Each project has a folder in `projects/`: its documents as Markdown files, AGENTS.md first, its folders as folders on disk, and `project.toml` with its repositories.
  The files are the master copy: written by the app, and read back as an editor or an agent changes them, a folder made there being a new project.
  A document written elsewhere while its page is open is never saved over: the page asks which version to keep.
  A document's name is its file's, ending in `.md`.
- Feature: Give a task the agent's side of its work: its repositories, acceptance criteria, outcome, pull requests and updates
  Its page shows them under the description, as Agent work: its project's repositories as toggles, what done means and what came of it, its pull requests with their state on GitHub, and the updates reported as it went.
- Feature: Let any agent report on a task in one call, `POST /api/tasks/<id>/report`, or MCP's `report_task`
  A note, the outcome, its pull requests, and how far it got, never further than needs review.
- Feature: Mark a task done once its pull requests all merge, read from GitHub every few minutes
- Feature: Launch a task on T3 Code from its page, in a workspace of its own across its repositories
  Its repositories are cloned into the everyday files when needed, a worktree of each made on the task's branch, and the agent given the task, what done means, the project's AGENTS.md and how to report back.
  The run is followed from T3: working, waiting on you, finished or failed moves the task with it, its pull requests are linked, and its worktrees go once the task is settled.
