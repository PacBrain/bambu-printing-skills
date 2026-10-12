"""Validate the portable folder payload; this is not native software validation."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKILLS = [p for p in (ROOT / "skills").iterdir() if (p / "SKILL.md").is_file()]


class PackageTest(unittest.TestCase):
    def test_portable_frontmatter(self):
        for skill in SKILLS:
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"))
            frontmatter = text.split("---", 2)[1]
            name = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
            description = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
            self.assertIsNotNone(name)
            self.assertIsNotNone(description)
            self.assertEqual(name.group(1).strip(), skill.name)
            self.assertRegex(skill.name, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
            self.assertLessEqual(len(skill.name), 64)
            self.assertLessEqual(len(description.group(1).strip()), 1024)
            self.assertLess(len(text.splitlines()), 500)

    def test_local_markdown_links_stay_in_payload(self):
        for skill in SKILLS:
            for document in skill.rglob("*.md"):
                text = document.read_text(encoding="utf-8")
                for match in re.finditer(r"\]\(([^)]+)\)", text):
                    target = match.group(1).strip().strip("<>").split(' "', 1)[0]
                    url = urlsplit(target)
                    if url.scheme or not url.path:
                        continue
                    resolved = (document.parent / unquote(url.path)).resolve()
                    self.assertTrue(resolved.is_relative_to(skill.resolve()), f"Reference escapes payload: {document}: {target}")
                    self.assertTrue(resolved.exists(), f"Missing reference: {document}: {target}")

    def test_source_references_have_bundled_records(self):
        for skill in SKILLS:
            records = json.loads((skill / "references" / "sources.json").read_text(encoding="utf-8"))
            identifiers = [record["id"] for record in records]
            self.assertEqual(len(identifiers), len(set(identifiers)), "Duplicate source IDs")
            for record in records:
                url = urlsplit(record["url"])
                self.assertIn(url.scheme, ("http", "https"))
                self.assertTrue(url.netloc)
                self.assertTrue(record["title"])
            for document in skill.rglob("*.md"):
                cited = set(re.findall(r"\b[BR]\d{2}\b", document.read_text(encoding="utf-8")))
                self.assertTrue(cited <= set(identifiers), f"Unknown source IDs in {document}: {cited - set(identifiers)}")

    def test_license_and_notice_travel_with_skill(self):
        for skill in SKILLS:
            for filename in ("LICENSE", "NOTICE.md"):
                self.assertEqual((ROOT / filename).read_bytes(), (skill / filename).read_bytes())

    def test_copied_helper_help_from_unrelated_cwd(self):
        for skill in SKILLS:
            with tempfile.TemporaryDirectory(prefix="Portable skill 空格 ") as directory:
                root = Path(directory)
                copied = root / "installed" / skill.name
                shutil.copytree(skill, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                cwd = root / "unrelated project"
                cwd.mkdir()
                script = "rhino_run.py" if skill.name == "rhino-modeling" else "bambu.py"
                result = subprocess.run([sys.executable, str(copied / "scripts" / script), "--help"], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout.lower())
                self.assertTrue((copied / "references").is_dir())
                if skill.name == "bambu-printing":
                    dependencies = (copied / "requirements.txt").read_text(encoding="utf-8")
                    self.assertIn("trimesh", dependencies)
                    self.assertEqual((ROOT / "requirements.txt").read_text(encoding="utf-8"), "-r skills/bambu-printing/requirements.txt\n")


if __name__ == "__main__":
    unittest.main()
