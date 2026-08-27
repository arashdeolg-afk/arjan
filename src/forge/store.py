"""Project storage: files on disk under a jailed per-project root.

The filesystem is the source of truth. A project is a directory under
``<data>/projects/<id>/`` holding the user's files plus one hidden
metadata file (``.forge.json``). Every path coming from the network goes
through :meth:`Store.resolve`, which rejects anything that would land
outside the project directory — including ``..`` tricks and symlink
escapes — before any read or write happens.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import re
import shutil
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import templates

META = ".forge.json"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SKIP_DIRS = {"__pycache__", ".git", "node_modules"}
MAX_TREE = 4000
MAX_FILE = 20 * 1024 * 1024  # 20 MB per file write
MAX_NAME = 80


class StoreError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:48] or "project"


class Store:
    def __init__(self, data_dir: str | os.PathLike):
        self.root = Path(data_dir)
        self.projects_dir = self.root / "projects"
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._versions: dict[str, int] = {}

    # ---------------------------------------------------------------- projects

    def _pdir(self, pid: str, must_exist: bool = True) -> Path:
        if not ID_RE.match(pid or ""):
            raise StoreError("invalid project id", 400)
        p = self.projects_dir / pid
        if must_exist and not (p / META).is_file():
            raise StoreError(f"no such project: {pid}", 404)
        return p

    def _read_meta(self, pdir: Path) -> dict:
        try:
            return json.loads((pdir / META).read_text("utf-8"))
        except (OSError, ValueError) as e:
            raise StoreError(f"unreadable project metadata: {e}", 500)

    def _write_meta(self, pdir: Path, meta: dict) -> None:
        (pdir / META).write_text(json.dumps(meta, indent=2) + "\n", "utf-8")

    def create(self, name: str, template: str = "blank") -> dict:
        name = (name or "").strip()
        if not name:
            raise StoreError("project name is required")
        if len(name) > MAX_NAME:
            raise StoreError(f"name too long (max {MAX_NAME} chars)")
        tpl = templates.TEMPLATES.get(template)
        if tpl is None:
            raise StoreError(f"unknown template: {template}")

        with self._lock:
            base = slugify(name)
            pid, n = base, 2
            while (self.projects_dir / pid).exists():
                pid, n = f"{base}-{n}", n + 1
            pdir = self.projects_dir / pid
            pdir.mkdir(parents=True)

        for rel, content in tpl["files"].items():
            path = pdir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, "utf-8")

        meta = {
            "id": pid,
            "name": name,
            "template": template,
            "kind": tpl["kind"],
            "run": tpl["run"],
            "entry": tpl["entry"],
            "created": _now(),
            "updated": _now(),
        }
        self._write_meta(pdir, meta)
        self.bump(pid)
        return meta

    def list_projects(self) -> list[dict]:
        out = []
        for pdir in sorted(self.projects_dir.iterdir()) if self.projects_dir.exists() else []:
            if pdir.is_dir() and (pdir / META).is_file():
                try:
                    out.append(self._read_meta(pdir))
                except StoreError:
                    continue
        out.sort(key=lambda m: m.get("updated", ""), reverse=True)
        return out

    def get_meta(self, pid: str) -> dict:
        return self._read_meta(self._pdir(pid))

    def update_meta(self, pid: str, patch: dict) -> dict:
        pdir = self._pdir(pid)
        meta = self._read_meta(pdir)
        for key in ("name", "run", "entry", "kind"):
            if key in patch:
                value = patch[key]
                if not isinstance(value, str):
                    raise StoreError(f"{key} must be a string")
                if key == "name":
                    value = value.strip()
                    if not value:
                        raise StoreError("project name is required")
                    if len(value) > MAX_NAME:
                        raise StoreError(f"name too long (max {MAX_NAME} chars)")
                if key == "kind" and value not in ("web", "console"):
                    raise StoreError("kind must be 'web' or 'console'")
                meta[key] = value
        meta["updated"] = _now()
        self._write_meta(pdir, meta)
        return meta

    def duplicate(self, pid: str, name: str | None = None) -> dict:
        src = self._pdir(pid)
        meta = self._read_meta(src)
        new_name = (name or f"{meta['name']} copy").strip()
        with self._lock:
            base = slugify(new_name)
            new_id, n = base, 2
            while (self.projects_dir / new_id).exists():
                new_id, n = f"{base}-{n}", n + 1
            shutil.copytree(src, self.projects_dir / new_id)
        meta.update(id=new_id, name=new_name, created=_now(), updated=_now())
        self._write_meta(self.projects_dir / new_id, meta)
        return meta

    def delete_project(self, pid: str) -> None:
        pdir = self._pdir(pid)
        shutil.rmtree(pdir)
        self._versions.pop(pid, None)

    # ------------------------------------------------------------------- files

    def resolve(self, pid: str, rel: str, allow_root: bool = False) -> Path:
        """Map a client-supplied relative path into the project jail."""
        pdir = self._pdir(pid)
        rel = (rel or "").replace("\\", "/").strip().strip("/")
        if not rel:
            if allow_root:
                return pdir
            raise StoreError("path is required")
        parts = PurePosixPath(rel).parts
        if any(p in ("..", ".") for p in parts):
            raise StoreError("path may not contain '.' or '..' segments", 403)
        if META in parts:
            raise StoreError(f"{META} is managed by forge", 403)
        target = (pdir / rel).resolve()
        root = pdir.resolve()
        if target != root and root not in target.parents:
            raise StoreError("path escapes the project", 403)
        return target

    def tree(self, pid: str) -> list[dict]:
        pdir = self._pdir(pid)
        entries: list[dict] = []

        def walk(d: Path, prefix: str) -> None:
            if len(entries) >= MAX_TREE:
                return
            children = sorted(
                d.iterdir(),
                key=lambda p: (p.is_file(), p.name.lower()),
            )
            for child in children:
                rel = f"{prefix}{child.name}"
                if child.name == META or child.name in SKIP_DIRS:
                    continue
                if child.is_symlink():
                    continue
                if child.is_dir():
                    entries.append({"path": rel, "type": "dir"})
                    walk(child, rel + "/")
                elif child.is_file():
                    entries.append(
                        {"path": rel, "type": "file", "size": child.stat().st_size}
                    )

        walk(pdir, "")
        return entries

    def read_file(self, pid: str, rel: str) -> dict:
        path = self.resolve(pid, rel)
        if path.is_dir():
            raise StoreError(f"{rel} is a directory")
        if not path.is_file():
            raise StoreError(f"no such file: {rel}", 404)
        data = path.read_bytes()
        try:
            return {"path": rel, "binary": False, "content": data.decode("utf-8"),
                    "size": len(data)}
        except UnicodeDecodeError:
            return {"path": rel, "binary": True, "content": None, "size": len(data)}

    def read_bytes(self, pid: str, rel: str) -> bytes:
        path = self.resolve(pid, rel)
        if not path.is_file():
            raise StoreError(f"no such file: {rel}", 404)
        return path.read_bytes()

    def write_file(self, pid: str, rel: str, content: str | None = None,
                   content_b64: str | None = None) -> dict:
        path = self.resolve(pid, rel)
        if path.is_dir():
            raise StoreError(f"{rel} is a directory")
        if content_b64 is not None:
            try:
                data = base64.b64decode(content_b64, validate=True)
            except (binascii.Error, ValueError):
                raise StoreError("content_b64 is not valid base64")
        else:
            data = (content or "").encode("utf-8")
        if len(data) > MAX_FILE:
            raise StoreError("file too large (max 20 MB)", 413)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self._touch(pid)
        return {"path": rel, "size": len(data)}

    def batch_write(self, pid: str, files: list[dict]) -> list[dict]:
        if not isinstance(files, list) or not files:
            raise StoreError("files must be a non-empty list")
        # Validate every path before writing anything, so a bad entry
        # can't leave a half-applied batch.
        for f in files:
            if not isinstance(f, dict) or not f.get("path"):
                raise StoreError("each file needs a path")
            self.resolve(pid, f["path"])
        return [
            self.write_file(pid, f["path"], f.get("content"), f.get("content_b64"))
            for f in files
        ]

    def mkdir(self, pid: str, rel: str) -> dict:
        path = self.resolve(pid, rel)
        path.mkdir(parents=True, exist_ok=True)
        self._touch(pid)
        return {"path": rel, "type": "dir"}

    def move(self, pid: str, src: str, dst: str) -> dict:
        spath = self.resolve(pid, src)
        dpath = self.resolve(pid, dst)
        if not spath.exists():
            raise StoreError(f"no such path: {src}", 404)
        if dpath.exists():
            raise StoreError(f"already exists: {dst}", 409)
        dpath.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(spath), str(dpath))
        self._touch(pid)
        return {"path": dst}

    def delete_path(self, pid: str, rel: str) -> None:
        path = self.resolve(pid, rel)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        else:
            raise StoreError(f"no such path: {rel}", 404)
        self._touch(pid)

    def export_zip(self, pid: str) -> bytes:
        pdir = self._pdir(pid)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in self.tree(pid):
                if entry["type"] == "file":
                    zf.write(pdir / entry["path"], entry["path"])
        return buf.getvalue()

    # ------------------------------------------------------- change tracking

    def _touch(self, pid: str) -> None:
        pdir = self._pdir(pid)
        meta = self._read_meta(pdir)
        meta["updated"] = _now()
        self._write_meta(pdir, meta)
        self.bump(pid)

    def bump(self, pid: str) -> int:
        with self._lock:
            self._versions[pid] = self.version(pid, _locked=True) + 1
            return self._versions[pid]

    def version(self, pid: str, _locked: bool = False) -> int:
        if not _locked:
            self._pdir(pid)  # 404 for unknown projects
        if pid not in self._versions:
            try:
                seed = int((self.projects_dir / pid / META).stat().st_mtime)
            except OSError:
                seed = 0
            self._versions[pid] = seed
        return self._versions[pid]

    # ---------------------------------------------------------------- settings

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.json"

    def get_settings(self) -> dict:
        try:
            return json.loads(self.settings_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def update_settings(self, patch: dict) -> dict:
        with self._lock:
            settings = self.get_settings()
            for key, value in patch.items():
                if value in (None, ""):
                    settings.pop(key, None)
                else:
                    settings[key] = value
            self.root.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(
                json.dumps(settings, indent=2) + "\n", "utf-8"
            )
            try:
                os.chmod(self.settings_path, 0o600)
            except OSError:
                pass
        return settings
