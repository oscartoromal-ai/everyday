- Feature: The app updates from GitHub's releases, so another laptop installs it and keeps it up to date too
  GitHub now builds every merge to master into a release: the installer, for a machine the app is not on yet, and the version itself, which every installed app downloads and stages for Restart to update as before.
  No machine needs the repo, git or Python to update any more.
  The repo being private, the app reads its releases with the GitHub CLI's sign-in, or a token pasted in Settings, where Check for updates asks for one when it has neither.
