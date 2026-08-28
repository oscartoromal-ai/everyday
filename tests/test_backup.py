from datetime import date

from sqlalchemy import text

from app.db import make_engine
from app.services import backup as backup_svc


def test_run_backup_writes_dated_snapshot(tmp_path) -> None:
    db_path = tmp_path / "personal-calendar.db"
    backup_dir = tmp_path / "backups"

    engine = make_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
        conn.execute(text("INSERT INTO t (v) VALUES ('hello')"))
    engine.dispose()

    today = date(2026, 8, 28)
    result = backup_svc.run_backup(db_path, backup_dir, retain=30, today=today)

    assert result == backup_dir / "personal-calendar-2026-08-28.db"
    assert result.exists()

    check_engine = make_engine(f"sqlite:///{result}")
    with check_engine.connect() as conn:
        rows = conn.execute(text("SELECT v FROM t")).fetchall()
    check_engine.dispose()
    assert rows == [("hello",)]


def test_prune_snapshots_keeps_only_newest_retain(tmp_path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for day in range(1, 6):
        (backup_dir / f"personal-calendar-2026-08-{day:02d}.db").write_bytes(b"x")

    deleted = backup_svc.prune_snapshots(backup_dir, retain=3)

    remaining = sorted(p.name for p in backup_dir.glob("personal-calendar-*.db"))
    assert remaining == [
        "personal-calendar-2026-08-03.db",
        "personal-calendar-2026-08-04.db",
        "personal-calendar-2026-08-05.db",
    ]
    assert {p.name for p in deleted} == {
        "personal-calendar-2026-08-01.db",
        "personal-calendar-2026-08-02.db",
    }


def test_run_backup_prunes_after_writing(tmp_path) -> None:
    db_path = tmp_path / "personal-calendar.db"
    backup_dir = tmp_path / "backups"
    engine = make_engine(f"sqlite:///{db_path}")
    engine.dispose()

    for day in range(1, 4):
        backup_svc.run_backup(db_path, backup_dir, retain=2, today=date(2026, 8, day))

    remaining = sorted(p.name for p in backup_dir.glob("personal-calendar-*.db"))
    assert remaining == [
        "personal-calendar-2026-08-02.db",
        "personal-calendar-2026-08-03.db",
    ]
