"""SQLite backup/restore utility for the mounted Toolbox database."""

from __future__ import annotations

import argparse
from pathlib import Path

from toolbox.infrastructure.backup import backup, restore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database", type=Path, required=True)
    backup_parser.add_argument("--output", type=Path, required=True)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--input", type=Path, required=True)
    restore_parser.add_argument("--database", type=Path, required=True)

    arguments = parser.parse_args()
    if arguments.operation == "backup":
        backup(arguments.database, arguments.output)
    else:
        restore(arguments.input, arguments.database)


if __name__ == "__main__":
    main()
