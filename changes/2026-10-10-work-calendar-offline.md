- Fix: The work calendar catches up once the network is back, instead of logging errors and waiting for the next day
  Waking the computer after its poll times ran every missed poll at once, before the network was up, so each logged an error and the work calendar stayed out of date until the next morning's poll.
  The app now looks every few minutes for a poll time that has passed: a wake runs one poll, an unreachable feed is noted and tried again a few minutes later, and the app polls soon after it starts too.
