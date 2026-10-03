#!/usr/bin/env python3
"""
Antigravity History Sync - Core Engine
Handles:
- Discovering Antigravity local paths on macOS, Windows, and Linux.
- Reading and validating ~/.gemini/antigravity-history/cache.json.
- SQLite WAL checkpointing and clean database packaging.
- Brain trajectory and artifact directory bundling.
- Cross-platform file URI and workspace path remapping.
- Non-destructive local cache merging with automated safety backups.
"""

import os
import sys
import json
import shutil
import sqlite3
import zipfile
import datetime
import tempfile
import re
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


def _decode_varint(data: bytes, pos: int) -> Tuple[int, int]:
    """Decodes a protobuf varint starting at pos. Returns (value, next_pos)."""
    res = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        res |= (b & 0x7F) << shift
        shift += 7
        if (b & 0x80) == 0:
            break
    return res, pos


def _encode_varint(val: int) -> bytes:
    """Encodes an integer into protobuf varint bytes."""
    res = bytearray()
    while val >= 0x80:
        res.append((val & 0x7F) | 0x80)
        val >>= 7
    res.append(val)
    return bytes(res)


class AntigravityPaths:
    """Detects and resolves standard Antigravity directories across platforms."""

    @staticmethod
    def get_base_dir() -> Path:
        """Returns the ~/.gemini directory."""
        return Path.home() / ".gemini"

    @classmethod
    def get_history_dir(cls) -> Path:
        """Returns ~/.gemini/antigravity-history."""
        return cls.get_base_dir() / "antigravity-history"

    @classmethod
    def get_cache_file(cls) -> Path:
        """Returns ~/.gemini/antigravity-history/cache.json."""
        return cls.get_history_dir() / "cache.json"

    @classmethod
    def get_ide_dir(cls) -> Path:
        """Returns ~/.gemini/antigravity-ide."""
        return cls.get_base_dir() / "antigravity-ide"

    @classmethod
    def get_conversations_dir(cls) -> Path:
        """Returns ~/.gemini/antigravity-ide/conversations."""
        return cls.get_ide_dir() / "conversations"

    @classmethod
    def get_brain_dir(cls) -> Path:
        """Returns ~/.gemini/antigravity-ide/brain."""
        return cls.get_ide_dir() / "brain"

    @classmethod
    def get_config_dir(cls) -> Path:
        """Returns ~/.gemini/config."""
        return cls.get_base_dir() / "config"

    @classmethod
    def get_backups_dir(cls) -> Path:
        """Returns ~/.gemini/antigravity-history/backups."""
        return cls.get_history_dir() / "backups"

    @classmethod
    def get_trash_dir(cls) -> Path:
        """Returns ~/.gemini/antigravity-history/trash."""
        return cls.get_history_dir() / "trash"

    @classmethod
    def get_vscdb_paths(cls) -> List[Path]:
        """Returns all discovered state.vscdb paths across profiles for Antigravity IDE."""
        paths: List[Path] = []
        if sys.platform == "darwin":
            base = Path.home() / "Library/Application Support/Antigravity IDE/User"
        elif sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "Antigravity IDE/User"
        else:
            base = Path.home() / ".config/Antigravity IDE/User"

        main_db = base / "globalStorage/state.vscdb"
        if main_db.exists():
            paths.append(main_db)

        profiles = base / "profiles"
        if profiles.exists():
            for p in profiles.glob("*/globalStorage/state.vscdb"):
                paths.append(p)
        return paths


class HistoryEngine:
    """Core engine for exporting, importing, checkpointing, and merging Antigravity chats."""

    VERSION = "1.0.0"

    def __init__(self, custom_base_dir: Optional[Path] = None):
        if custom_base_dir:
            self.base_dir = custom_base_dir
            self.history_dir = self.base_dir / "antigravity-history"
            self.cache_file = self.history_dir / "cache.json"
            self.ide_dir = self.base_dir / "antigravity-ide"
            self.conversations_dir = self.ide_dir / "conversations"
            self.brain_dir = self.ide_dir / "brain"
            self.config_dir = self.base_dir / "config"
            self.backups_dir = self.history_dir / "backups"
            self.trash_dir = self.history_dir / "trash"
        else:
            self.base_dir = AntigravityPaths.get_base_dir()
            self.history_dir = AntigravityPaths.get_history_dir()
            self.cache_file = AntigravityPaths.get_cache_file()
            self.ide_dir = AntigravityPaths.get_ide_dir()
            self.conversations_dir = AntigravityPaths.get_conversations_dir()
            self.brain_dir = AntigravityPaths.get_brain_dir()
            self.config_dir = AntigravityPaths.get_config_dir()
            self.backups_dir = AntigravityPaths.get_backups_dir()
            self.trash_dir = AntigravityPaths.get_trash_dir()

    def read_cache(self) -> Dict[str, Any]:
        """Reads and parses cache.json safely."""
        if not self.cache_file.exists():
            return {"version": 1, "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "conversations": {}}
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Warning: Error reading cache file {self.cache_file}: {e}", file=sys.stderr)
            return {"version": 1, "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "conversations": {}}

    def write_cache_atomic(self, cache_data: Dict[str, Any]) -> None:
        """Atomically writes cache.json using a temp file to avoid file corruption."""
        self.history_dir.mkdir(parents=True, exist_ok=True)
        temp_fd, temp_path = tempfile.mkstemp(dir=self.history_dir, prefix="cache_temp_", suffix=".json")
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, self.cache_file)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def read_vscdb_summaries(self) -> Dict[str, bytes]:
        """
        Reads all conversation chunks from local Antigravity state.vscdb databases.
        Returns a dictionary mapping conversation_id -> raw protobuf chunk bytes.
        """
        summaries: Dict[str, bytes] = {}
        for db_path in AntigravityPaths.get_vscdb_paths():
            if not db_path.exists():
                continue
            try:
                conn = sqlite3.connect(str(db_path))
                cur = conn.cursor()
                cur.execute("SELECT value FROM ItemTable WHERE key = 'antigravityUnifiedStateSync.trajectorySummaries'")
                row = cur.fetchone()
                conn.close()
                if not row or not row[0]:
                    continue
                raw = base64.b64decode(row[0])
                pos = 0
                while pos < len(raw):
                    try:
                        tag, pos = _decode_varint(raw, pos)
                        length, pos = _decode_varint(raw, pos)
                        chunk = raw[pos : pos + length]
                        pos += length

                        cpos = 0
                        c_id = None
                        while cpos < len(chunk):
                            ctag, cpos = _decode_varint(chunk, cpos)
                            cfn = ctag >> 3
                            clen, cpos = _decode_varint(chunk, cpos)
                            cval = chunk[cpos : cpos + clen]
                            cpos += clen
                            if cfn == 1:
                                c_id = cval.decode("utf-8", errors="ignore")
                        if c_id:
                            summaries[c_id] = chunk
                    except Exception:
                        break
            except Exception as e:
                print(f"[!] Warning: Could not read summaries from {db_path}: {e}", file=sys.stderr)
        return summaries

    def merge_vscdb_summaries(self, new_summaries: Dict[str, bytes]) -> int:
        """
        Merges conversation summary chunks into all discovered local state.vscdb databases
        so that synced conversations immediately appear in the Antigravity 'Past Conversations' list.
        Returns the number of newly added summaries.
        """
        if not new_summaries:
            return 0

        target_paths = AntigravityPaths.get_vscdb_paths()
        if not target_paths:
            if sys.platform == "darwin":
                default_p = Path.home() / "Library/Application Support/Antigravity IDE/User/globalStorage/state.vscdb"
            elif sys.platform == "win32":
                default_p = Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "Antigravity IDE/User/globalStorage/state.vscdb"
            else:
                default_p = Path.home() / ".config/Antigravity IDE/User/globalStorage/state.vscdb"
            target_paths = [default_p]

        merged_total = 0
        for db_path in target_paths:
            try:
                db_path.parent.mkdir(parents=True, exist_ok=True)
                existing = {}
                if db_path.exists():
                    conn = sqlite3.connect(str(db_path))
                    cur = conn.cursor()
                    try:
                        cur.execute("SELECT value FROM ItemTable WHERE key = 'antigravityUnifiedStateSync.trajectorySummaries'")
                        row = cur.fetchone()
                        if row and row[0]:
                            raw = base64.b64decode(row[0])
                            pos = 0
                            while pos < len(raw):
                                tag, pos = _decode_varint(raw, pos)
                                length, pos = _decode_varint(raw, pos)
                                chunk = raw[pos : pos + length]
                                pos += length
                                cpos = 0
                                c_id = None
                                while cpos < len(chunk):
                                    ctag, cpos = _decode_varint(chunk, cpos)
                                    cfn = ctag >> 3
                                    clen, cpos = _decode_varint(chunk, cpos)
                                    cval = chunk[cpos : cpos + clen]
                                    cpos += clen
                                    if cfn == 1:
                                        c_id = cval.decode("utf-8", errors="ignore")
                                if c_id:
                                    existing[c_id] = chunk
                    except Exception:
                        pass
                    conn.close()

                # Merge new summaries into existing
                count_added = 0
                for c_id, chunk in new_summaries.items():
                    if c_id not in existing:
                        count_added += 1
                    existing[c_id] = chunk

                # Reconstruct protobuf
                reconstructed = bytearray()
                tag_bytes = _encode_varint((1 << 3) | 2)
                for chunk in existing.values():
                    reconstructed.extend(tag_bytes)
                    reconstructed.extend(_encode_varint(len(chunk)))
                    reconstructed.extend(chunk)

                b64_val = base64.b64encode(reconstructed).decode("ascii")

                conn = sqlite3.connect(str(db_path))
                cur = conn.cursor()
                cur.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
                cur.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES ('antigravityUnifiedStateSync.trajectorySummaries', ?)", (b64_val,))
                conn.commit()
                conn.close()

                merged_total += count_added
            except Exception as e:
                print(f"[!] Warning: Failed to merge summaries into {db_path}: {e}", file=sys.stderr)

        return merged_total

    @staticmethod
    def build_synthetic_summary_chunk(c_id: str, title: str, traj_id: Optional[str] = None, workspace_uri: str = "") -> bytes:
        """Constructs a valid protobuf summary chunk for conversations lacking one."""
        def make_str(fn: int, s: str) -> bytes:
            d = s.encode("utf-8")
            return _encode_varint((fn << 3) | 2) + _encode_varint(len(d)) + d

        def make_int(fn: int, v: int) -> bytes:
            return _encode_varint((fn << 3) | 0) + _encode_varint(v)

        inner = bytearray()
        inner.extend(make_str(1, title or "Untitled Conversation"))
        inner.extend(make_int(2, 10))
        inner.extend(make_str(4, traj_id or c_id))
        inner.extend(make_int(5, 1))
        if workspace_uri:
            inner.extend(make_str(9, workspace_uri))
        inner.extend(make_int(22, 4))

        inner_b64 = base64.b64encode(inner).decode("ascii")
        sub1 = make_str(1, inner_b64)
        field2 = _encode_varint((2 << 3) | 2) + _encode_varint(len(sub1)) + sub1

        chunk = bytearray()
        chunk.extend(make_str(1, c_id))
        chunk.extend(field2)
        return bytes(chunk)

    def list_conversations(self) -> List[Dict[str, Any]]:
        """Returns a list of all conversations with statistics."""
        cache = self.read_cache()
        convs = []
        for conv_id, meta in cache.get("conversations", {}).items():
            db_path = self.conversations_dir / f"{conv_id}.db"
            brain_path = self.brain_dir / conv_id
            
            db_size = db_path.stat().st_size if db_path.exists() else 0
            has_brain = brain_path.exists()

            workspaces = []
            if "workspaces" in meta and isinstance(meta["workspaces"], list):
                for ws in meta["workspaces"]:
                    if isinstance(ws, dict) and "workspaceFolderAbsoluteUri" in ws:
                        workspaces.append(ws["workspaceFolderAbsoluteUri"])

            convs.append({
                "id": conv_id,
                "summary": meta.get("summary", "Untitled Conversation"),
                "createdTime": meta.get("createdTime", ""),
                "lastModifiedTime": meta.get("lastModifiedTime", ""),
                "stepCount": meta.get("stepCount", 0),
                "db_size": db_size,
                "has_brain": has_brain,
                "workspaces": workspaces,
                "metadata": meta,
            })

        # Sort newest first
        convs.sort(key=lambda x: x.get("lastModifiedTime", ""), reverse=True)
        return convs

    def checkpoint_sqlite_db(self, src_db: Path, target_db: Path) -> None:
        """
        Checkpoints WAL and creates a clean standalone copy of the SQLite database.
        Falls back to safe file copy if sqlite3 locking prevents VACUUM.
        """
        target_db.parent.mkdir(parents=True, exist_ok=True)
        if not src_db.exists():
            return

        wal_file = src_db.parent / f"{src_db.name}-wal"
        shm_file = src_db.parent / f"{src_db.name}-shm"

        try:
            # Try connecting read-only to trigger passive checkpoint or vacuum
            conn = sqlite3.connect(f"file:{src_db.resolve()}?mode=ro", uri=True)
            try:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            except Exception:
                pass
            
            # Vacuum into a fresh clean single file without WAL dependencies
            try:
                conn.execute(f"VACUUM INTO '{target_db.resolve()}';")
                conn.close()
                return
            except Exception:
                conn.close()
        except Exception:
            pass

        # Fallback: copy .db and .db-wal / .db-shm directly
        shutil.copy2(src_db, target_db)
        if wal_file.exists():
            shutil.copy2(wal_file, target_db.parent / f"{target_db.name}-wal")
        if shm_file.exists():
            shutil.copy2(shm_file, target_db.parent / f"{target_db.name}-shm")

    def export_archive(
        self,
        output_zip_path: Path,
        conversation_ids: Optional[List[str]] = None,
        filter_project: Optional[str] = None,
        include_media: bool = True
    ) -> Dict[str, Any]:
        """
        Exports conversations into a standard portable ZIP file.
        Includes manifest.json, cache_fragment.json, conversations/, and brain/.
        """
        output_zip_path = Path(output_zip_path)
        output_zip_path.parent.mkdir(parents=True, exist_ok=True)

        cache = self.read_cache()
        all_convs = cache.get("conversations", {})

        # Filter target conversation IDs
        target_ids = []
        for c_id, meta in all_convs.items():
            if conversation_ids and c_id not in conversation_ids:
                continue
            if filter_project:
                matches_project = False
                workspaces = meta.get("workspaces", [])
                for ws in workspaces:
                    uri = ws.get("workspaceFolderAbsoluteUri", "") if isinstance(ws, dict) else ""
                    if filter_project.lower() in uri.lower():
                        matches_project = True
                        break
                if not matches_project:
                    continue
            target_ids.append(c_id)

        if not target_ids:
            return {"success": False, "count": 0, "error": "No conversations matched the export criteria."}

        cache_fragment = {
            "version": 1,
            "updatedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "conversations": {c_id: all_convs[c_id] for c_id in target_ids if c_id in all_convs}
        }

        manifest = {
            "tool": "antigravity-history-sync",
            "version": self.VERSION,
            "exportDate": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "sourcePlatform": sys.platform,
            "userHome": str(Path.home()),
            "conversationCount": len(target_ids),
            "conversationIds": target_ids,
            "includesMedia": include_media,
        }

        with tempfile.TemporaryDirectory(prefix="agy_export_") as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Write manifest and cache fragment
            with open(tmp_path / "manifest.json", "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            with open(tmp_path / "cache_fragment.json", "w", encoding="utf-8") as f:
                json.dump(cache_fragment, f, indent=2, ensure_ascii=False)

            # Checkpoint and copy databases
            convs_tmp = tmp_path / "conversations"
            convs_tmp.mkdir(parents=True, exist_ok=True)

            brain_tmp = tmp_path / "brain"
            brain_tmp.mkdir(parents=True, exist_ok=True)

            summaries_tmp = tmp_path / "summaries"
            summaries_tmp.mkdir(parents=True, exist_ok=True)
            local_summaries = self.read_vscdb_summaries()

            exported_count = 0
            for c_id in target_ids:
                src_db = self.conversations_dir / f"{c_id}.db"
                if src_db.exists():
                    target_db = convs_tmp / f"{c_id}.db"
                    self.checkpoint_sqlite_db(src_db, target_db)

                src_brain = self.brain_dir / c_id
                if src_brain.exists():
                    target_brain = brain_tmp / c_id
                    
                    def ignore_func(src, names):
                        ignored = set()
                        if not include_media:
                            if ".user_uploaded" in names:
                                ignored.add(".user_uploaded")
                        return ignored

                    shutil.copytree(src_brain, target_brain, ignore=ignore_func, dirs_exist_ok=True)

                # Export trajectory summary chunk for Antigravity IDE recent history
                summary_chunk = local_summaries.get(c_id)
                if not summary_chunk:
                    meta = all_convs.get(c_id, {})
                    title = meta.get("summary", "Untitled Conversation")
                    ws_uri = ""
                    workspaces = meta.get("workspaces", [])
                    if workspaces and isinstance(workspaces[0], dict):
                        ws_uri = workspaces[0].get("workspaceFolderAbsoluteUri", "")
                    summary_chunk = self.build_synthetic_summary_chunk(c_id, title, workspace_uri=ws_uri)

                if summary_chunk:
                    with open(summaries_tmp / f"{c_id}.summary", "wb") as sf:
                        sf.write(summary_chunk)

                exported_count += 1

            # Build ZIP archive
            with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_out:
                for root, _, files in os.walk(tmp_path):
                    for file in files:
                        full_fpath = Path(root) / file
                        rel_path = full_fpath.relative_to(tmp_path)
                        zip_out.write(full_fpath, arcname=str(rel_path))

        return {
            "success": True,
            "archivePath": str(output_zip_path),
            "count": exported_count,
            "fileSize": output_zip_path.stat().st_size
        }

    @staticmethod
    def remap_uri(
        uri: str,
        source_home: Optional[str] = None,
        target_home: Optional[str] = None,
        custom_mappings: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Remaps file:// URIs between platforms and home directories.
        E.g. file:///Users/alice/projects -> file:///C:/Users/bob/projects or file:///home/bob/projects.
        """
        if not uri:
            return uri

        # Apply custom mappings first
        if custom_mappings:
            for old_p, new_p in custom_mappings.items():
                if old_p in uri:
                    uri = uri.replace(old_p, new_p)

        # Detect source POSIX vs Windows
        if source_home and target_home and source_home != target_home:
            # Normalize home representations
            norm_source_uri = source_home.replace("\\", "/")
            norm_target_uri = target_home.replace("\\", "/")
            if norm_source_uri.startswith("/"):
                source_uri_pattern = f"file://{norm_source_uri}"
            else:
                source_uri_pattern = f"file:///{norm_source_uri}"

            if norm_target_uri.startswith("/"):
                target_uri_pattern = f"file://{norm_target_uri}"
            else:
                target_uri_pattern = f"file:///{norm_target_uri}"

            if source_uri_pattern in uri:
                uri = uri.replace(source_uri_pattern, target_uri_pattern)
            elif norm_source_uri in uri:
                uri = uri.replace(norm_source_uri, norm_target_uri)

        return uri

    def import_archive(
        self,
        zip_archive_path: Path,
        conflict_strategy: str = "newer",  # "newer", "overwrite", or "skip"
        custom_path_remaps: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Imports conversations from a ZIP archive.
        - Creates a safety backup of local cache.json first.
        - Merges conversations safely.
        - Automatically remaps cross-platform workspace paths.
        - Preserves existing conversations on the local machine.
        """
        zip_archive_path = Path(zip_archive_path)
        if not zip_archive_path.exists():
            return {"success": False, "count": 0, "error": f"Archive file {zip_archive_path} does not exist."}

        # Step 1: Create local safety backup
        backup_stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.cache_file.exists():
            try:
                self.backups_dir.mkdir(parents=True, exist_ok=True)
                safety_backup = self.backups_dir / f"cache_backup_{backup_stamp}.json"
                shutil.copy2(self.cache_file, safety_backup)
            except Exception as e:
                safety_backup = None
                print(f"[!] Warning: Could not create safety backup: {e}", file=sys.stderr)
        else:
            safety_backup = None

        with tempfile.TemporaryDirectory(prefix="agy_import_") as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Unpack zip
            with zipfile.ZipFile(zip_archive_path, "r") as zip_in:
                zip_in.extractall(tmp_path)

            manifest_file = tmp_path / "manifest.json"
            fragment_file = tmp_path / "cache_fragment.json"

            if not fragment_file.exists():
                return {"success": False, "count": 0, "error": "Invalid archive: cache_fragment.json missing."}

            manifest = {}
            if manifest_file.exists():
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)

            with open(fragment_file, "r", encoding="utf-8") as f:
                incoming_fragment = json.load(f)

            source_home = manifest.get("userHome")
            target_home = str(Path.home())

            local_cache = self.read_cache()
            local_convs = local_cache.setdefault("conversations", {})

            incoming_convs = incoming_fragment.get("conversations", {})
            imported_count = 0
            skipped_count = 0
            updated_count = 0

            self.conversations_dir.mkdir(parents=True, exist_ok=True)
            self.brain_dir.mkdir(parents=True, exist_ok=True)

            incoming_conv_dir = tmp_path / "conversations"
            incoming_brain_dir = tmp_path / "brain"

            for c_id, in_meta in incoming_convs.items():
                should_import = True

                if c_id in local_convs:
                    if conflict_strategy == "skip":
                        skipped_count += 1
                        continue
                    elif conflict_strategy == "newer":
                        local_time = local_convs[c_id].get("lastModifiedTime", "")
                        incoming_time = in_meta.get("lastModifiedTime", "")
                        if local_time >= incoming_time:
                            skipped_count += 1
                            continue
                        else:
                            updated_count += 1
                    elif conflict_strategy == "overwrite":
                        updated_count += 1
                else:
                    imported_count += 1

                # Remap workspace paths in metadata
                remapped_meta = dict(in_meta)
                if "workspaces" in remapped_meta and isinstance(remapped_meta["workspaces"], list):
                    new_workspaces = []
                    for ws in remapped_meta["workspaces"]:
                        if isinstance(ws, dict):
                            new_ws = dict(ws)
                            if "workspaceFolderAbsoluteUri" in new_ws:
                                new_ws["workspaceFolderAbsoluteUri"] = self.remap_uri(
                                    new_ws["workspaceFolderAbsoluteUri"], source_home, target_home, custom_path_remaps
                                )
                            if "gitRootAbsoluteUri" in new_ws:
                                new_ws["gitRootAbsoluteUri"] = self.remap_uri(
                                    new_ws["gitRootAbsoluteUri"], source_home, target_home, custom_path_remaps
                                )
                            new_workspaces.append(new_ws)
                        else:
                            new_workspaces.append(ws)
                    remapped_meta["workspaces"] = new_workspaces

                if "trajectoryMetadata" in remapped_meta and isinstance(remapped_meta["trajectoryMetadata"], dict):
                    traj = dict(remapped_meta["trajectoryMetadata"])
                    if "workspaceUris" in traj and isinstance(traj["workspaceUris"], list):
                        traj["workspaceUris"] = [
                            self.remap_uri(u, source_home, target_home, custom_path_remaps) for u in traj["workspaceUris"]
                        ]
                    remapped_meta["trajectoryMetadata"] = traj

                # Copy conversation DB
                src_db = incoming_conv_dir / f"{c_id}.db"
                if src_db.exists():
                    dest_db = self.conversations_dir / f"{c_id}.db"
                    shutil.copy2(src_db, dest_db)

                # Copy WAL/SHM if present
                src_wal = incoming_conv_dir / f"{c_id}.db-wal"
                if src_wal.exists():
                    shutil.copy2(src_wal, self.conversations_dir / f"{c_id}.db-wal")
                src_shm = incoming_conv_dir / f"{c_id}.db-shm"
                if src_shm.exists():
                    shutil.copy2(src_shm, self.conversations_dir / f"{c_id}.db-shm")

                # Copy Brain directory
                src_brain = incoming_brain_dir / c_id
                if src_brain.exists():
                    dest_brain = self.brain_dir / c_id
                    shutil.copytree(src_brain, dest_brain, dirs_exist_ok=True)

                # Save into local cache
                local_convs[c_id] = remapped_meta

            # Merge trajectory summaries into local state.vscdb so they appear in 'Past Conversations'
            incoming_summaries_dir = tmp_path / "summaries"
            summaries_to_merge = {}
            if incoming_summaries_dir.exists():
                for sf in incoming_summaries_dir.glob("*.summary"):
                    c_id = sf.stem
                    try:
                        with open(sf, "rb") as f:
                            summaries_to_merge[c_id] = f.read()
                    except Exception:
                        pass

            if summaries_to_merge:
                self.merge_vscdb_summaries(summaries_to_merge)

            # Save updated cache.json atomically
            local_cache["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.write_cache_atomic(local_cache)

        return {
            "success": True,
            "totalProcessed": len(incoming_convs),
            "newImported": imported_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "safetyBackup": str(safety_backup) if safety_backup else None
        }
