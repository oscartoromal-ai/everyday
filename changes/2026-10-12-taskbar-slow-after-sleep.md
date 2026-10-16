- Fix: The nudges' count no longer fails when the taskbar is slow to answer, as just after the PC wakes
  When Windows gave up waiting on the taskbar, the app logged an error and left both the taskbar button and the tray icon without their count for a minute.
  The tray icon now counts regardless, and the taskbar is asked again a few seconds later.
