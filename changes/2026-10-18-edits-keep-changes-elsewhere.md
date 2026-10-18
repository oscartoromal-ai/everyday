- Fix: Writing on a task no longer undoes what changed on it elsewhere
  A task's page, its sheet in a list and Today's notes used to save the whole task as they had it, so a status, a due or a description changed meanwhile (a pull request merging, Claude, another window) went back to what they showed.
  They now save only what you changed there.
