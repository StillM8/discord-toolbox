from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2] / "src" / "toolbox"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
    return found


def _files(package: str) -> tuple[Path, ...]:
    return tuple((ROOT / package).rglob("*.py"))


def test_core_has_no_outer_framework_or_adapter_imports() -> None:
    forbidden = (
        "discord",
        "sqlalchemy",
        "openai",
        "openai_codex",
        "toolbox.interfaces",
        "toolbox.providers",
        "toolbox.storage",
        "toolbox.infrastructure",
    )
    for path in _files("core"):
        assert not any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for imported in _imports(path)
            for prefix in forbidden
        ), path


def test_provider_and_storage_adapters_do_not_import_discord() -> None:
    for package in ("providers", "storage"):
        for path in _files(package):
            assert not any(
                imported == "discord" or imported.startswith("discord.")
                for imported in _imports(path)
            ), path


def test_discord_interface_does_not_import_provider_or_storage_implementations() -> None:
    forbidden = ("toolbox.providers", "toolbox.storage", "openai", "openai_codex", "sqlalchemy")
    for path in _files("interfaces/discord"):
        assert not any(
            imported == prefix or imported.startswith(f"{prefix}.")
            for imported in _imports(path)
            for prefix in forbidden
        ), path


def test_capabilities_and_workflows_do_not_import_outer_implementations() -> None:
    forbidden = (
        "toolbox.providers",
        "toolbox.storage",
        "toolbox.infrastructure",
        "toolbox.interfaces.discord",
    )
    for package in ("capabilities", "workflows"):
        for path in _files(package):
            assert not any(
                imported == prefix or imported.startswith(f"{prefix}.")
                for imported in _imports(path)
                for prefix in forbidden
            ), path
