- Feature: Everything written in the planner is a Markdown file in the everyday files, for an AI to explore as easily as the app
  Each task is task.md in its folder, which sits in its project's folder and moves with it: its fields as front matter, then its description, acceptance criteria and outcome.
  A project has project.md beside its documents, and each day's notes are notebook/<year>/<day>.md, written as on Today.
  The planner owns the fields: an edit to the front matter is put back. The words are the file's: written there, by an editor or an agent, they are the task's, the project's or the day's a moment later.
  A folder made in a project's tasks/ with a task.md in it is a new task.
  README.md at the folder's top says what is where, how each file reads, and how to query the database.
- Feature: Ctrl+K finds words in the files of projects and tasks, and Claude can search every file
- Feature: The daily backup zips the everyday files beside the database's snapshot
- Fix: A document or a task's file renamed on its page and then deleted from its bin is deleted
  The bin still named the file as it was called before, so nothing was deleted.
