- Fix: A new task never takes the id of one deleted
  A task added after the newest one was deleted used to get its id, and with it the deleted task's history (its History showed it written and deleted) and any of its files not yet in the trash.
  Every task now gets an id no task has had; the database is updated as the app starts.
