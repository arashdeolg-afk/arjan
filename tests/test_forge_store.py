"""Store tests: project CRUD, the path jail, and change tracking.

Run: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forge.store import META, Store, StoreError  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestProjects(Base):
    def test_create_from_template_writes_files_and_meta(self):
        meta = self.store.create("My Site", "website")
        self.assertEqual(meta["id"], "my-site")
        self.assertEqual(meta["kind"], "web")
        paths = {e["path"] for e in self.store.tree("my-site")}
        self.assertIn("index.html", paths)
        self.assertIn("style.css", paths)
        self.assertNotIn(META, paths)

    def test_name_collision_gets_suffix(self):
        first = self.store.create("Same", "blank")
        second = self.store.create("Same", "blank")
        self.assertEqual(first["id"], "same")
        self.assertEqual(second["id"], "same-2")

    def test_create_rejects_empty_name_and_bad_template(self):
        with self.assertRaises(StoreError):
            self.store.create("   ", "blank")
        with self.assertRaises(StoreError):
            self.store.create("ok", "not-a-template")

    def test_list_sorted_by_updated(self):
        self.store.create("Older", "blank")
        b = self.store.create("Newer", "blank")
        self.store.write_file(b["id"], "x.txt", "bump")
        names = [m["name"] for m in self.store.list_projects()]
        self.assertEqual(names[0], "Newer")

    def test_rename_and_run_command(self):
        meta = self.store.create("Original", "python")
        updated = self.store.update_meta(meta["id"], {"name": "Renamed",
                                                      "run": "python3 -u app.py"})
        self.assertEqual(updated["name"], "Renamed")
        self.assertEqual(updated["run"], "python3 -u app.py")
        self.assertEqual(self.store.get_meta(meta["id"])["name"], "Renamed")

    def test_duplicate_copies_files_under_new_id(self):
        meta = self.store.create("Site", "website")
        copy = self.store.duplicate(meta["id"])
        self.assertNotEqual(copy["id"], meta["id"])
        original = self.store.read_file(meta["id"], "index.html")["content"]
        cloned = self.store.read_file(copy["id"], "index.html")["content"]
        self.assertEqual(original, cloned)

    def test_delete_project(self):
        meta = self.store.create("Doomed", "blank")
        self.store.delete_project(meta["id"])
        with self.assertRaises(StoreError):
            self.store.get_meta(meta["id"])

    def test_webapp_template_carries_port(self):
        self.assertEqual(self.store.create("Server", "webapp")["port"], 8000)
        self.assertEqual(self.store.create("Site", "website")["port"], 0)

    def test_unknown_project_is_404(self):
        with self.assertRaises(StoreError) as ctx:
            self.store.get_meta("nope")
        self.assertEqual(ctx.exception.status, 404)


class TestPathJail(Base):
    def setUp(self) -> None:
        super().setUp()
        self.pid = self.store.create("Jail", "blank")["id"]

    def assert_denied(self, rel):
        with self.assertRaises(StoreError, msg=f"{rel!r} should be denied"):
            self.store.resolve(self.pid, rel)

    def test_traversal_variants_denied(self):
        for rel in ("../x", "a/../../x", "..", "a/b/../../../etc/passwd",
                    "./../x", "a\\..\\..\\x"):
            self.assert_denied(rel)

    def test_absolute_path_stays_inside_jail(self):
        # A leading slash is treated as project-relative, never filesystem-root.
        target = self.store.resolve(self.pid, "/etc/passwd")
        root = self.store.resolve(self.pid, "", allow_root=True)
        self.assertIn(root, target.parents)

    def test_meta_file_is_protected(self):
        self.assert_denied(META)
        self.assert_denied(f"sub/{META}")
        with self.assertRaises(StoreError):
            self.store.write_file(self.pid, META, "{}")
        with self.assertRaises(StoreError):
            self.store.delete_path(self.pid, META)

    def test_symlink_escape_denied(self):
        if os.name != "posix":
            self.skipTest("symlinks")
        root = self.store.resolve(self.pid, "", allow_root=True)
        (root / "link").symlink_to("/etc")
        with self.assertRaises(StoreError):
            self.store.read_file(self.pid, "link/passwd")

    def test_batch_validates_all_paths_before_writing(self):
        with self.assertRaises(StoreError):
            self.store.batch_write(self.pid, [
                {"path": "good.txt", "content": "ok"},
                {"path": "../evil.txt", "content": "no"},
            ])
        paths = {e["path"] for e in self.store.tree(self.pid)}
        self.assertNotIn("good.txt", paths)


class TestFiles(Base):
    def setUp(self) -> None:
        super().setUp()
        self.pid = self.store.create("Files", "blank")["id"]

    def test_write_read_roundtrip_creates_parents(self):
        self.store.write_file(self.pid, "a/b/c.txt", "hello")
        out = self.store.read_file(self.pid, "a/b/c.txt")
        self.assertEqual(out["content"], "hello")
        self.assertFalse(out["binary"])

    def test_binary_write_and_detection(self):
        import base64
        payload = base64.b64encode(b"\x89PNG\r\n\x1a\n\x00").decode()
        self.store.write_file(self.pid, "img.png", content_b64=payload)
        out = self.store.read_file(self.pid, "img.png")
        self.assertTrue(out["binary"])
        self.assertIsNone(out["content"])
        self.assertEqual(self.store.read_bytes(self.pid, "img.png")[:4], b"\x89PNG")

    def test_move_and_delete(self):
        self.store.write_file(self.pid, "old.txt", "x")
        self.store.move(self.pid, "old.txt", "dir/new.txt")
        self.assertEqual(self.store.read_file(self.pid, "dir/new.txt")["content"], "x")
        with self.assertRaises(StoreError):
            self.store.read_file(self.pid, "old.txt")
        self.store.delete_path(self.pid, "dir")
        paths = {e["path"] for e in self.store.tree(self.pid)}
        self.assertNotIn("dir", paths)

    def test_move_refuses_overwrite(self):
        self.store.write_file(self.pid, "a.txt", "a")
        self.store.write_file(self.pid, "b.txt", "b")
        with self.assertRaises(StoreError):
            self.store.move(self.pid, "a.txt", "b.txt")

    def test_tree_nests_and_sorts_dirs_first(self):
        self.store.write_file(self.pid, "z.txt", "")
        self.store.mkdir(self.pid, "assets")
        self.store.write_file(self.pid, "assets/logo.svg", "<svg/>")
        tree = self.store.tree(self.pid)
        self.assertEqual(tree[0], {"path": "assets", "type": "dir"})
        self.assertEqual(tree[1]["path"], "assets/logo.svg")

    def test_export_zip_contains_files_but_not_meta(self):
        self.store.write_file(self.pid, "sub/inner.txt", "inner")
        data = self.store.export_zip(self.pid)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            self.assertIn("sub/inner.txt", names)
            self.assertIn("README.md", names)
            self.assertNotIn(META, names)
            self.assertEqual(zf.read("sub/inner.txt"), b"inner")

    def test_version_bumps_on_writes(self):
        v1 = self.store.version(self.pid)
        self.store.write_file(self.pid, "x.txt", "1")
        v2 = self.store.version(self.pid)
        self.assertGreater(v2, v1)
        self.store.delete_path(self.pid, "x.txt")
        self.assertGreater(self.store.version(self.pid), v2)


class TestSettings(Base):
    def test_settings_roundtrip_and_key_removal(self):
        self.store.update_settings({"anthropic_api_key": "sk-test", "model": "m"})
        self.assertEqual(self.store.get_settings()["anthropic_api_key"], "sk-test")
        self.store.update_settings({"anthropic_api_key": ""})
        self.assertNotIn("anthropic_api_key", self.store.get_settings())
        self.assertEqual(self.store.get_settings()["model"], "m")


if __name__ == "__main__":
    unittest.main()
