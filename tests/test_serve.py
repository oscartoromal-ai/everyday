import logging
import sys
import threading

from app import serve


def test_the_hidden_app_logs_to_a_file(tmp_path, monkeypatch) -> None:
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    path = tmp_path / "logs" / "personal-calendar.log"
    try:
        serve._configure_logging(path)
        # uvicorn runs with log_config=None, so its loggers reach the file too.
        logging.getLogger("uvicorn.error").info("Uvicorn running")
        logging.getLogger("app.serve").info("Shutting down: console closed (SIGBREAK)")
        for handler in root.handlers:
            handler.flush()
        text = path.read_text(encoding="utf-8")
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers[:], root.level = saved[0], saved[1]
    assert "uvicorn.error: Uvicorn running" in text
    assert "Shutting down: console closed (SIGBREAK)" in text
