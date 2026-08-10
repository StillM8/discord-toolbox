from __future__ import annotations

import sqlite3
from pathlib import Path

from toolbox.infrastructure.backup import backup, restore


def test_sqlite_backup_and_restore_use_online_backup_api(tmp_path: Path) -> None:
    database = tmp_path / "toolbox.sqlite3"
    backup_path = tmp_path / "backup.sqlite3"
    restored = tmp_path / "restored.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("create table values_table (value text not null)")
        connection.execute("insert into values_table values ('safe')")
        connection.commit()

    backup(database, backup_path)
    restore(backup_path, restored)

    with sqlite3.connect(restored) as connection:
        row = connection.execute("select value from values_table").fetchone()
    assert row == ("safe",)
