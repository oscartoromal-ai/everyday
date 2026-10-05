"""A stand-in for a version of the app started to stand by (test_standby.py):
it waits as the app does (app/desktop/standby.py), writes where it was told
to come up (null when not), and says Up."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.desktop.standby import Waiting

instance, parent, given, data, out = sys.argv[1:]
waiting = Waiting(instance, int(parent), given, Path(data))
handover = waiting.wait_for_go()
Path(out).write_text(json.dumps(asdict(handover) if handover else None), encoding="utf-8")
if handover:
    waiting.up()
