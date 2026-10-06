- Fix: An update can no longer lose data, or leave the app unable to start, as it migrates the database
  A migration that changed a table no longer deletes what refers to it (a task's updates, pull requests and runs went with it), and one that fails halfway leaves the database as it was rather than half-changed for good.
  The database is copied before each migration, into `data/before-migrating/` in the app's home.
  An update that migrates the database and then does not come up has it put back, so the version before it starts again instead of saying it is older than its data.
