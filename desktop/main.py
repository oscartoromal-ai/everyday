"""The installed app's entry script (personal-calendar.spec): the app, or with
--self-check, its check of a build of itself (app/selfcheck.py). Frozen into
the program itself, so any change to it needs a build that freezes anew."""

import sys

if sys.argv[1:2] == ["--self-check"]:
    from app import selfcheck

    selfcheck.main(sys.argv[2:])
else:
    from app.desktop import main

    main()
