#!/usr/bin/env python3
"""Install Agent Skills into a chosen skill directory without replacing other skills."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile

IGNORED_NAMES = {"__pycache__", ".venv", ".DS_Store"}


def ignored(directory, names):
    """Runtime caches are not part of the distributable skill."""
    return {name for name in names if name in IGNORED_NAMES or name.endswith((".pyc", ".pyo"))}


def same_tree(source, destination):
    """Compare complete distributable contents, not timestamps or file sizes alone."""
    if not destination.is_dir() or destination.is_symlink():
        return False
    source_names = {p.name for p in source.iterdir()} - ignored(source, [p.name for p in source.iterdir()])
    destination_names = {p.name for p in destination.iterdir()} - ignored(destination, [p.name for p in destination.iterdir()])
    if source_names != destination_names:
        return False
    for name in source_names:
        a, b = source / name, destination / name
        if a.is_symlink() or b.is_symlink():
            if not (a.is_symlink() and b.is_symlink() and os.readlink(a) == os.readlink(b)):
                return False
        elif a.is_dir():
            if not same_tree(a, b):
                return False
        elif not b.is_file() or a.read_bytes() != b.read_bytes():
            return False
    return True


def install(source, destination, mode="copy", dry_run=False):
    source_path = source.resolve()
    destination_path = destination.resolve()
    if destination_path != source_path and destination_path.is_relative_to(source_path):
        raise ValueError("Destination must not be nested inside the source skill: " + str(destination))
    if destination.is_symlink() and destination.resolve() == source.resolve():
        return "Already installed: " + str(destination)
    if destination.exists() or destination.is_symlink():
        if same_tree(source, destination):
            return "Already installed: " + str(destination)
        raise FileExistsError("Refusing to replace existing skill: " + str(destination))
    if dry_run:
        return f"Would {mode}: {source} -> {destination}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mode == "symlink":
        try:
            destination.symlink_to(source, target_is_directory=True)
        except OSError as exc:
            raise OSError("Cannot create skill symlink; use --mode copy: " + str(exc)) from exc
    else:
        # Stage a complete payload beside its destination before exposing it.
        with tempfile.TemporaryDirectory(prefix=".skill-install-", dir=destination.parent) as staging:
            payload = Path(staging) / source.name
            shutil.copytree(source, payload, ignore=ignored, symlinks=True)
            if destination.exists() or destination.is_symlink():
                raise FileExistsError("Destination appeared during installation: " + str(destination))
            payload.rename(destination)
    return "Installed: " + str(destination)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    destinations = parser.add_mutually_exclusive_group()
    destinations.add_argument("--dest", type=Path, help="Skill-parent directory; default: ~/.agents/skills")
    destinations.add_argument("--codex-home", type=Path, help="Legacy alias: install under DIR/skills")
    parser.add_argument("--mode", choices=("copy", "symlink"), default="copy", help="Copy by default; symlink keeps a development checkout linked")
    parser.add_argument("--dry-run", action="store_true", help="Check and show the destination without writing files")
    args = parser.parse_args(argv)
    destination_root = args.dest or (args.codex_home / "skills" if args.codex_home else Path.home() / ".agents" / "skills")
    destination_root = destination_root.expanduser().absolute()
    source_root = Path(__file__).resolve().parent / "skills"
    sources = sorted(p for p in source_root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())
    if not sources:
        parser.error("No skill directories found beside this installer")
    # Check every destination before installing any skill.
    for source in sources:
        install(source, destination_root / source.name, args.mode, dry_run=True)
    for source in sources:
        print(install(source, destination_root / source.name, args.mode, args.dry_run))
    return 0


if __name__ == "__main__":
    # Keep machine-captured paths readable on Windows with a legacy locale.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
