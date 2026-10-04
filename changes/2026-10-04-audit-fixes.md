- Fix: The daily backup is taken even when the computer sleeps through 03:30
  A run missed while it slept runs on waking, a day with no snapshot yet takes one soon after the app starts, and the morning digest is dropped rather than sent more than two hours late.
- Fix: A Garmin sync no longer stops the rest of the app from saving while it runs
- Fix: A save waiting on the database no longer holds up every other page
- Fix: On a phone, scrolling Calendar's sheet no longer ticks habits or starts tasks, and scrolling the calendar no longer moves events
- Fix: Task rows written on Today just before leaving it are added, and added once
- Fix: A task being edited on Projects is saved when the page is left by a key (Alt and a number, Ctrl+K)
- Fix: A due-soon nudge goes once its task's due day moves
