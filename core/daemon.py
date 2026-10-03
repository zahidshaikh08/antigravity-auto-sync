#!/usr/bin/env python3
"""
Antigravity History Sync - Sync Daemon & Coordinator
Handles:
- Two-way delta synchronization between local Antigravity storage and Google Drive.
- Checkpoint & packaging of local changed conversations.
- Download, cross-platform path remapping, and non-destructive merge of remote conversations.
- Debounced background file watching with offline retry queue.
"""

import os
import sys
import time
import json
import base64
import tempfile
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.engine import HistoryEngine, AntigravityPaths
from core.gdrive import GDriveSyncClient


class SyncCoordinator:
    """Orchestrates bidirectional sync between local Antigravity and Google Drive."""

    def __init__(self, engine: Optional[HistoryEngine] = None, gdrive: Optional[GDriveSyncClient] = None):
        self.engine = engine or HistoryEngine()
        self.gdrive = gdrive or GDriveSyncClient()
        self.state_file = self.engine.history_dir / "sync_state.json"

    def load_sync_state(self) -> Dict[str, Any]:
        """Loads last sync timestamp, device ID, and hashes."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "lastSyncTime": "",
            "syncedConversations": {},
            "deviceId": os.uname().nodename if hasattr(os, "uname") else "desktop-node",
            "excludedConversations": []
        }

    def save_sync_state(self, state: Dict[str, Any]) -> None:
        """Saves sync state to disk."""
        self.engine.history_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def is_excluded(self, conversation_id: str, metadata: Dict[str, Any], state: Dict[str, Any]) -> bool:
        """Checks if a conversation is marked as local-only / excluded from sync."""
        if conversation_id in state.get("excludedConversations", []):
            return True
        # Check project exclusions
        workspaces = metadata.get("workspaces", [])
        for ws in workspaces:
            uri = ws.get("workspaceFolderAbsoluteUri", "") if isinstance(ws, dict) else ""
            if ".agents/sync_exclude" in uri:
                return True
        return False

    def sync_cycle(self, conflict_strategy: str = "newer", verbose: bool = True) -> Dict[str, Any]:
        """
        Executes a complete 2-way sync cycle:
        1. Authenticate with Google Drive.
        2. Read local cache.json and remote registry.json.
        3. Identify conversations to upload (local is newer or missing remotely).
        4. Identify conversations to download (remote is newer or missing locally).
        5. Perform atomic transfers, WAL checkpoints, path remapping, and cache merges.
        """
        if not self.gdrive.is_authenticated():
            return {"success": False, "error": "Google Drive is not connected. Run 'agy-sync login' first."}

        sync_state = self.load_sync_state()

        if verbose:
            print("[*] Contacting Google Drive...")

        try:
            folder_id = self.gdrive.get_or_create_sync_folder()
            convs_folder_id = self.gdrive.get_or_create_subfolder(folder_id, "conversations")
            remote_registry = self.gdrive.get_remote_registry(folder_id)

            local_cache = self.engine.read_cache()
            local_convs = local_cache.get("conversations", {})
            remote_convs = remote_registry.get("conversations", {})

            uploaded_count = 0
            downloaded_count = 0
            skipped_count = 0

            # Step A: Identify and upload newer local conversations
            local_vscdb_sums = self.engine.read_vscdb_summaries()
            with tempfile.TemporaryDirectory(prefix="agy_sync_") as tmp_dir:
                tmp_path = Path(tmp_dir)

                for c_id, l_meta in local_convs.items():
                    if self.is_excluded(c_id, l_meta, sync_state):
                        continue

                    l_modified = l_meta.get("lastModifiedTime", "")
                    r_meta = remote_convs.get(c_id)
                    r_modified = r_meta.get("lastModifiedTime", "") if r_meta else ""

                    if not r_meta or l_modified > r_modified:
                        if verbose:
                            print(f"  ▲ Uploading: {l_meta.get('summary', c_id[:8])}...")
                        
                        zip_out = tmp_path / f"{c_id}.agyzip"
                        res = self.engine.export_archive(zip_out, conversation_ids=[c_id])
                        if res["success"]:
                            file_id = self.gdrive.upload_file(convs_folder_id, f"{c_id}.agyzip", zip_out)
                            # Get summary chunk
                            s_chunk = local_vscdb_sums.get(c_id)
                            s_b64 = base64.b64encode(s_chunk).decode("ascii") if s_chunk else ""

                            # Update remote registry entry
                            remote_convs[c_id] = {
                                "summary": l_meta.get("summary", ""),
                                "createdTime": l_meta.get("createdTime", ""),
                                "lastModifiedTime": l_modified,
                                "stepCount": l_meta.get("stepCount", 0),
                                "workspaces": l_meta.get("workspaces", []),
                                "trajectoryMetadata": l_meta.get("trajectoryMetadata", {}),
                                "trajectorySummaryB64": s_b64,
                                "fileId": file_id,
                                "lastSyncedBy": sync_state.get("deviceId", "node")
                            }
                            uploaded_count += 1
                            if zip_out.exists():
                                zip_out.unlink()

                # Step B: Identify and download newer remote conversations
                downloaded_summaries = {}
                for c_id, r_meta in remote_convs.items():
                    l_meta = local_convs.get(c_id)
                    l_modified = l_meta.get("lastModifiedTime", "") if l_meta else ""
                    r_modified = r_meta.get("lastModifiedTime", "")

                    if not l_meta or r_modified > l_modified:
                        file_id = r_meta.get("fileId")
                        if not file_id:
                            continue

                        if verbose:
                            print(f"  ▼ Downloading: {r_meta.get('summary', c_id[:8])}...")

                        zip_in = tmp_path / f"{c_id}_in.agyzip"
                        try:
                            self.gdrive.download_file(file_id, zip_in)
                            imp_res = self.engine.import_archive(zip_in, conflict_strategy=conflict_strategy)
                            if imp_res["success"]:
                                downloaded_count += 1
                                if r_meta.get("trajectorySummaryB64"):
                                    try:
                                        downloaded_summaries[c_id] = base64.b64decode(r_meta["trajectorySummaryB64"])
                                    except Exception:
                                        pass
                        except Exception as e:
                            print(f"[!] Warning: Failed to download conversation {c_id}: {e}", file=sys.stderr)
                        finally:
                            if zip_in.exists():
                                zip_in.unlink()

                if downloaded_summaries:
                    self.engine.merge_vscdb_summaries(downloaded_summaries)

                # Step B.2: Ensure all remote conversations are indexed in local Antigravity state.vscdb
                fresh_local_sums = self.engine.read_vscdb_summaries()
                missing_vscdb = {}
                for c_id, r_meta in remote_convs.items():
                    if c_id not in fresh_local_sums and r_meta.get("trajectorySummaryB64"):
                        try:
                            missing_vscdb[c_id] = base64.b64decode(r_meta["trajectorySummaryB64"])
                        except Exception:
                            pass
                if missing_vscdb:
                    added_count = self.engine.merge_vscdb_summaries(missing_vscdb)
                    if verbose:
                        print(f"  ✔ Restored {added_count} conversation(s) into Antigravity Past Conversations index.")

                # Check if remote registry lacks trajectorySummaryB64 for conversations existing locally
                registry_needs_update = uploaded_count > 0
                for c_id, r_meta in remote_convs.items():
                    if not r_meta.get("trajectorySummaryB64") and c_id in local_vscdb_sums:
                        r_meta["trajectorySummaryB64"] = base64.b64encode(local_vscdb_sums[c_id]).decode("ascii")
                        registry_needs_update = True

                # Step C: Save updated remote registry back to Google Drive
                if registry_needs_update:
                    remote_registry["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    remote_registry["conversations"] = remote_convs

                    reg_file = tmp_path / "registry.json"
                    with open(reg_file, "w", encoding="utf-8") as f:
                        json.dump(remote_registry, f, indent=2, ensure_ascii=False)

                    self.gdrive.upload_file(folder_id, "registry.json", reg_file, mime_type="application/json")

            sync_state["lastSyncTime"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.save_sync_state(sync_state)

            return {
                "success": True,
                "uploaded": uploaded_count,
                "downloaded": downloaded_count,
                "lastSyncTime": sync_state["lastSyncTime"]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def start_daemon_watcher(self, interval_seconds: int = 30) -> None:
        """Runs a lightweight polling/watcher daemon in the background."""
        print(f"[*] Starting Antigravity Sync Daemon (Polling every {interval_seconds}s)...")
        print("[*] Press Ctrl+C to terminate.")

        # Step 1: Immediate Startup Sync on launch
        try:
            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Running startup sync with Google Drive...")
            res = self.sync_cycle(verbose=True)
            if res["success"]:
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ✔ Synced (Uploaded: {res['uploaded']}, Downloaded: {res['downloaded']})")
            else:
                print(f"[!] Startup sync error: {res.get('error')}", file=sys.stderr)
        except Exception as e:
            print(f"[!] Startup sync exception: {e}", file=sys.stderr)

        # Step 2: Background Watcher & Poller Loop
        last_mtime = self.engine.cache_file.stat().st_mtime if self.engine.cache_file.exists() else 0.0
        last_remote_check = time.time()

        while True:
            try:
                time.sleep(5)
                now = time.time()

                # Check A: Local modifications to cache.json
                local_changed = False
                if self.engine.cache_file.exists():
                    current_mtime = self.engine.cache_file.stat().st_mtime
                    if current_mtime > last_mtime:
                        last_mtime = current_mtime
                        local_changed = True
                        # Debounce wait for agent file writes to finish
                        time.sleep(3)
                        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Detected local chat changes. Running sync...")
                        res = self.sync_cycle(verbose=True)
                        last_remote_check = now
                        if res["success"]:
                            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ✔ Synced (Uploaded: {res['uploaded']}, Downloaded: {res['downloaded']})")
                            if self.engine.cache_file.exists():
                                last_mtime = self.engine.cache_file.stat().st_mtime
                        else:
                            print(f"\n[!] Sync error:\n{res.get('error')}\n", file=sys.stderr)

                # Check B: Periodic Remote Polling (every interval_seconds)
                if not local_changed and (now - last_remote_check >= interval_seconds):
                    last_remote_check = now
                    res = self.sync_cycle(verbose=False)
                    if res["success"]:
                        if res["downloaded"] > 0 or res["uploaded"] > 0:
                            print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ✔ Synced (Uploaded: {res['uploaded']}, Downloaded: {res['downloaded']})")
                            if self.engine.cache_file.exists():
                                last_mtime = self.engine.cache_file.stat().st_mtime
                    else:
                        print(f"[!] Remote poll error: {res.get('error')}", file=sys.stderr)

            except KeyboardInterrupt:
                print("\n[*] Sync daemon stopped.")
                break
            except Exception as e:
                print(f"[!] Error in sync daemon loop:\n{e}\n", file=sys.stderr)
                time.sleep(interval_seconds)

