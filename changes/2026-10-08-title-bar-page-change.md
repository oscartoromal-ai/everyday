- Fix: Moving to another page while the app is busy no longer logs an error
  Each page tells the desktop window what colours and title its title bar should have.
  The window used to send back a reply, and if a new page had opened by the time the reply came, that page could not take it, so the app logged an error.
  The page now tells the window through a channel that sends nothing back, both for the title bar and for a dismissed nudge.
