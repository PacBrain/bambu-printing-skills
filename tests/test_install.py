"""Installer contract tests: isolated destinations, no host agent required."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("skill_installer", ROOT / "install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Skill install 空格 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source" / "example-skill"
        self.source.mkdir(parents=True)
        (self.source / "SKILL.md").write_text("---\nname: example-skill\ndescription: Example\n---\n模型\n", encoding="utf-8")
        (self.source / "references").mkdir()
        (self.source / "references" / "guide.md").write_text("Guide\n", encoding="utf-8")
        self.destination = self.root / "custom skills" / self.source.name

    def make_symlink(self, destination, target):
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("Symlink privilege unavailable: " + str(exc))

    def test_copy_and_identical_reinstall(self):
        installer.install(self.source, self.destination)
        self.assertFalse(self.destination.is_symlink())
        self.assertTrue(installer.same_tree(self.source, self.destination))
        self.assertIn("Already installed", installer.install(self.source, self.destination))
        self.assertEqual((self.source / "SKILL.md").read_bytes(), (self.destination / "SKILL.md").read_bytes())

    def test_changed_copy_refused_without_modification(self):
        installer.install(self.source, self.destination)
        changed = self.destination / "SKILL.md"
        changed.write_text("User-owned content\n", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "Refusing"):
            installer.install(self.source, self.destination)
        self.assertEqual(changed.read_text(encoding="utf-8"), "User-owned content\n")

    def test_extra_destination_file_refused(self):
        installer.install(self.source, self.destination)
        (self.destination / "user.md").write_text("Keep me", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            installer.install(self.source, self.destination)

    def test_file_conflict_refused(self):
        self.destination.parent.mkdir()
        self.destination.write_text("Keep me", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            installer.install(self.source, self.destination)

    def test_dry_run_does_not_create_parent(self):
        result = installer.install(self.source, self.destination, dry_run=True)
        self.assertIn("Would copy", result)
        self.assertFalse(self.destination.parent.exists())

    def test_destination_inside_source_rejected_before_writing(self):
        nested = self.source / "nested" / "example-skill"
        for dry_run in (False, True):
            with self.assertRaisesRegex(ValueError, "nested inside"):
                installer.install(self.source, nested, dry_run=dry_run)
        self.assertFalse(nested.parent.exists())

    def test_same_source_directory_is_already_installed(self):
        self.assertIn("Already installed", installer.install(self.source, self.source))

    def test_symlink_install_and_reinstall(self):
        probe = self.root / "probe"
        self.make_symlink(probe, self.source)
        probe.unlink()
        installer.install(self.source, self.destination, mode="symlink")
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(self.destination.resolve(), self.source.resolve())
        self.assertIn("Already installed", installer.install(self.source, self.destination, mode="symlink"))
        self.assertIn("Already installed", installer.install(self.source, self.destination, mode="copy"))

    def test_unrelated_and_broken_symlinks_refused(self):
        target = self.root / "unrelated"
        target.mkdir()
        self.make_symlink(self.destination, target)
        with self.assertRaises(FileExistsError):
            installer.install(self.source, self.destination)
        target.rmdir()
        with self.assertRaises(FileExistsError):
            installer.install(self.source, self.destination)
        self.assertTrue(self.destination.is_symlink())

    def test_runtime_caches_are_not_distributed(self):
        cache = self.source / "__pycache__"
        cache.mkdir()
        (cache / "example.pyc").write_bytes(b"cache")
        (self.source / ".DS_Store").write_bytes(b"cache")
        installer.install(self.source, self.destination)
        self.assertFalse((self.destination / "__pycache__").exists())
        self.assertFalse((self.destination / ".DS_Store").exists())
        self.assertTrue(installer.same_tree(self.source, self.destination))

    def test_default_is_neutral_and_ignores_codex_environment(self):
        capture = io.StringIO()
        with patch.object(installer.Path, "home", return_value=self.root), patch.dict(os.environ, {"CODEX_HOME": str(self.root / "legacy")}), contextlib.redirect_stdout(capture):
            installer.main(["--dry-run"])
        self.assertIn(str(self.root / ".agents" / "skills"), capture.getvalue())
        self.assertNotIn(str(self.root / "legacy"), capture.getvalue())
        self.assertFalse((self.root / ".agents").exists())

    def test_cli_custom_destination_from_unrelated_cwd(self):
        result = subprocess.run([sys.executable, str(ROOT / "install.py"), "--dest", str(self.root / "target")], cwd=self.root, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        for source in (ROOT / "skills").iterdir():
            if (source / "SKILL.md").is_file():
                self.assertTrue((self.root / "target" / source.name / "SKILL.md").is_file())

    def test_legacy_explicit_home_appends_skills(self):
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            installer.main(["--codex-home", str(self.root / "legacy"), "--dry-run"])
        self.assertIn(str(self.root / "legacy" / "skills"), capture.getvalue())
        self.assertFalse((self.root / "legacy").exists())

    def test_destination_options_are_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            installer.main(["--dest", str(self.root), "--codex-home", str(self.root)])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
