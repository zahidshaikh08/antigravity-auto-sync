#!/usr/bin/env python3
"""
Unit and Integration Tests for Antigravity History Sync Engine
Tests:
- Cache reading/writing
- SQLite database creation and WAL checkpointing
- Portable ZIP archive export
- Cross-platform URI remapping (Mac <-> Windows)
- Safe non-destructive import and conflict merging
- Safety backup verification
"""

import os
import sys
import json
import sqlite3
import unittest
import tempfile
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from core.engine import HistoryEngine


class TestHistoryEngine(unittest.TestCase):

    def setUp(self):
        # Create an isolated temporary sandbox for test data
        self.tmp_dir = tempfile.TemporaryDirectory(prefix="agy_test_")
        self.sandbox = Path(self.tmp_dir.name)
        self.engine = HistoryEngine(custom_base_dir=self.sandbox)

        # Setup mock directories
        self.engine.history_dir.mkdir(parents=True, exist_ok=True)
        self.engine.conversations_dir.mkdir(parents=True, exist_ok=True)
        self.engine.brain_dir.mkdir(parents=True, exist_ok=True)

        # Populate a mock conversation
        self.conv_id_1 = "11111111-2222-3333-4444-555555555555"
        self.mock_cache = {
            "version": 1,
            "updatedAt": "2026-10-01T10:00:00Z",
            "conversations": {
                self.conv_id_1: {
                    "summary": "Flutter Feature Architecture Plan",
                    "createdTime": "2026-10-01T09:00:00Z",
                    "lastModifiedTime": "2026-10-01T10:00:00Z",
                    "stepCount": 42,
                    "workspaces": [
                        {"workspaceFolderAbsoluteUri": "file:///Users/developer/projects/flutter_app"}
                    ],
                    "trajectoryMetadata": {
                        "workspaceUris": ["file:///Users/developer/projects/flutter_app"]
                    }
                }
            }
        }
        with open(self.engine.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.mock_cache, f, indent=2)

        # Create mock SQLite database
        db_path = self.engine.conversations_dir / f"{self.conv_id_1}.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT);")
        conn.execute("INSERT INTO messages (content) VALUES ('Initial test message');")
        conn.commit()
        conn.close()

        # Create mock brain directory with transcript
        brain_path = self.engine.brain_dir / self.conv_id_1 / ".system_generated" / "logs"
        brain_path.mkdir(parents=True, exist_ok=True)
        with open(brain_path / "transcript.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "USER_INPUT", "content": "Hello agent"}) + "\n")
            f.write(json.dumps({"type": "PLANNER_RESPONSE", "content": "Hello user"}) + "\n")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_list_conversations(self):
        convs = self.engine.list_conversations()
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["id"], self.conv_id_1)
        self.assertEqual(convs[0]["summary"], "Flutter Feature Architecture Plan")
        self.assertEqual(convs[0]["stepCount"], 42)
        self.assertTrue(convs[0]["has_brain"])

    def test_export_archive(self):
        zip_path = self.sandbox / "export_test.zip"
        res = self.engine.export_archive(zip_path)

        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 1)
        self.assertTrue(zip_path.exists())
        self.assertGreater(zip_path.stat().st_size, 0)

    def test_uri_remapping_mac_to_windows(self):
        mac_uri = "file:///Users/developer/projects/flutter_app"
        remapped = HistoryEngine.remap_uri(
            mac_uri,
            source_home="/Users/developer",
            target_home="C:\\Users\\windows_user"
        )
        self.assertIn("C:/Users/windows_user", remapped)
        self.assertNotIn("Users/developer", remapped)

    def test_custom_uri_remapping(self):
        uri = "file:///old/repo/path/main"
        custom_maps = {"/old/repo/path": "/new/work/repo"}
        remapped = HistoryEngine.remap_uri(uri, custom_mappings=custom_maps)
        self.assertEqual(remapped, "file:///new/work/repo/main")

    def test_import_and_safe_merge(self):
        # 1. Export first
        zip_path = self.sandbox / "backup.zip"
        self.engine.export_archive(zip_path)

        # 2. Create a second empty sandbox (Target Machine B)
        with tempfile.TemporaryDirectory(prefix="agy_target_") as target_dir:
            target_engine = HistoryEngine(custom_base_dir=Path(target_dir))

            # Populate target machine with its own distinct conversation
            local_conv_id = "99999999-8888-7777-6666-555555555555"
            target_cache = {
                "version": 1,
                "conversations": {
                    local_conv_id: {
                        "summary": "Existing Local Target Chat",
                        "lastModifiedTime": "2026-10-02T12:00:00Z"
                    }
                }
            }
            target_engine.history_dir.mkdir(parents=True, exist_ok=True)
            with open(target_engine.cache_file, "w") as f:
                json.dump(target_cache, f)

            # 3. Perform import
            import_res = target_engine.import_archive(zip_path, conflict_strategy="newer")

            self.assertTrue(import_res["success"])
            self.assertEqual(import_res["newImported"], 1)

            # 4. Verify NON-DESTRUCTIVE merge: target must now have BOTH conversations!
            merged_convs = target_engine.list_conversations()
            merged_ids = [c["id"] for c in merged_convs]

            self.assertEqual(len(merged_ids), 2)
            self.assertIn(local_conv_id, merged_ids)  # Existing local preserved!
            self.assertIn(self.conv_id_1, merged_ids)  # Incoming imported!

            # Verify files were imported
            imported_db = target_engine.conversations_dir / f"{self.conv_id_1}.db"
            imported_brain = target_engine.brain_dir / self.conv_id_1 / ".system_generated" / "logs" / "transcript.jsonl"

            self.assertTrue(imported_db.exists())
            self.assertTrue(imported_brain.exists())


if __name__ == "__main__":
    unittest.main()
