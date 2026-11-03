#!/usr/bin/env python3
"""
Unit and Integration Tests for Antigravity Backup & Restore Tool
Tests backup generation, archive verification, inspection, safety restore points,
and restoration in an isolated temporary environment.
"""

import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

# Add script directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from antigravity_backup import (
    calculate_sha256,
    encode_field,
    encode_timestamp,
    encode_varint,
    get_convo_details,
    inspect_backup,
    list_backups,
    read_manifest,
    rebuild_summaries_proto,
    run_backup,
    run_restore,
    verify_backup,
)


class TestAntigravityBackupTool(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary test workspace
        self.test_dir = tempfile.mkdtemp(prefix="test_agy_backup_")
        self.test_path = pathlib.Path(self.test_dir)

        # Mock ~/.gemini folder structure
        self.mock_gemini = self.test_path / ".gemini"
        self.mock_antigravity = self.mock_gemini / "antigravity"
        self.mock_convos = self.mock_antigravity / "conversations"
        self.mock_brain = self.mock_antigravity / "brain"
        self.mock_config = self.mock_gemini / "config" / "skills" / "my-skill"
        self.mock_cache = self.mock_antigravity / "cache"

        # Create directories
        self.mock_convos.mkdir(parents=True, exist_ok=True)
        self.mock_brain.mkdir(parents=True, exist_ok=True)
        self.mock_config.mkdir(parents=True, exist_ok=True)
        self.mock_cache.mkdir(parents=True, exist_ok=True)

        # Backup destination folder
        self.backup_dest = self.test_path / "backups"
        self.backup_dest.mkdir(parents=True, exist_ok=True)

        # Create mock SQLite conversation databases
        self.sample_db_1 = self.mock_convos / "convo_1.db"
        self._create_mock_conversation_db(
            self.sample_db_1,
            trajectory_id="traj-111",
            cascade_id="casc-111",
            title="Fixing POS bug",
        )

        self.sample_db_2 = self.mock_convos / "convo_2.db"
        self._create_mock_conversation_db(
            self.sample_db_2,
            trajectory_id="traj-222",
            cascade_id="casc-222",
            title="Building NextJS App",
        )

        # Create sample brain transcript and artifact inside .system_generated/logs
        convo_brain = self.mock_brain / "casc-111" / ".system_generated" / "logs"
        convo_brain.mkdir(parents=True, exist_ok=True)
        (convo_brain / "transcript.jsonl").write_text(
            json.dumps({"type": "USER_INPUT", "content": "How do I fix POS bug?"}) + "\n",
            encoding="utf-8",
        )

        # Create sample skill file
        (self.mock_config / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: test skill\n---\n# My Skill Documentation\n",
            encoding="utf-8",
        )

        # Create a cache file that SHOULD be excluded
        (self.mock_cache / "temp_cache.bin").write_bytes(b"TEMPORARY_CACHE_DATA_SHOULD_BE_EXCLUDED")

    def tearDown(self):
        # Cleanup temp directory
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_conversation_db(self, db_path, trajectory_id, cascade_id, title):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE trajectory_meta (trajectory_id TEXT, cascade_id TEXT)")
        cur.execute(
            "INSERT INTO trajectory_meta VALUES (?, ?)",
            (trajectory_id, cascade_id),
        )

        cur.execute("CREATE TABLE trajectory_metadata_blob (id TEXT, data BLOB)")
        cur.execute("INSERT INTO trajectory_metadata_blob VALUES ('main', x'0102')")

        cur.execute(
            "CREATE TABLE steps (idx INTEGER, step_type TEXT, status TEXT, metadata BLOB, step_payload BLOB)"
        )

        # Insert sample step with title encoded in proto field 4
        title_bytes = title.encode("utf-8")
        title_field = encode_field(4, 2, title_bytes)
        step_payload = title_field

        cur.execute(
            "INSERT INTO steps VALUES (0, 'USER_INPUT', 'DONE', NULL, ?)",
            (step_payload,),
        )
        conn.commit()
        conn.close()

    def test_backup_creation_and_exclusions(self):
        """Verifies that run_backup creates a valid zip, excludes cache, and writes correct manifest."""
        zip_path = run_backup(
            gemini_dir=self.mock_gemini,
            dest_dir=self.backup_dest,
            include_cache=False,
            tag="test_run",
            force=True,
            quiet=True,
        )

        self.assertTrue(zip_path.exists())
        self.assertTrue(zipfile.is_zipfile(zip_path))

        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = zf.namelist()
            # 1. Manifest must be present
            self.assertIn("manifest.json", namelist)

            # 2. Database files must be present
            self.assertTrue(any("conversations/convo_1.db" in name for name in namelist))
            self.assertTrue(any("conversations/convo_2.db" in name for name in namelist))

            # 3. Brain files must be present
            self.assertTrue(any("transcript.jsonl" in name for name in namelist))

            # 4. Cache files must be EXCLUDED
            self.assertFalse(any("temp_cache.bin" in name for name in namelist))

        # Check manifest contents
        manifest = read_manifest(zip_path)
        self.assertEqual(manifest["total_conversations"], 2)
        self.assertEqual(manifest["tag"], "test_run")
        self.assertIn("checksums", manifest)
        self.assertGreater(len(manifest["checksums"]), 0)

    def test_verify_backup_integrity(self):
        """Verifies that verify_backup detects intact archives and catches corruption and checksum tampering."""
        zip_path = run_backup(
            gemini_dir=self.mock_gemini,
            dest_dir=self.backup_dest,
            force=True,
            quiet=True,
        )

        # Clean backup should pass
        self.assertTrue(verify_backup(zip_path, quiet=True))

        # Test A: Corrupt header (unreadable zip)
        corrupt_zip = self.backup_dest / "corrupt_backup.zip"
        with open(zip_path, "rb") as f:
            data = bytearray(f.read())
        data[:16] = b"\x00" * 16
        with open(corrupt_zip, "wb") as f:
            f.write(data)

        self.assertFalse(verify_backup(corrupt_zip, quiet=True))

        # Test B: Checksum mismatch (tampered content)
        tampered_zip = self.backup_dest / "tampered_backup.zip"
        with zipfile.ZipFile(zip_path, "r") as src_zf:
            with zipfile.ZipFile(tampered_zip, "w") as dst_zf:
                for item in src_zf.infolist():
                    content = src_zf.read(item.filename)
                    if item.filename == "manifest.json":
                        m = json.loads(content.decode("utf-8"))
                        # Tamper one checksum
                        first_key = list(m["checksums"].keys())[0]
                        m["checksums"][first_key] = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
                        content = json.dumps(m).encode("utf-8")
                    dst_zf.writestr(item, content)

        self.assertFalse(verify_backup(tampered_zip, quiet=True))

    def test_restore_and_safety_point(self):
        """Verifies that run_restore extracts data properly and automatically creates a safety point."""
        # 1. Create a backup
        zip_path = run_backup(
            gemini_dir=self.mock_gemini,
            dest_dir=self.backup_dest,
            force=True,
            quiet=True,
        )

        # 2. Prepare a new empty target directory representing a new PC
        new_gemini = self.test_path / "new_gemini_env"

        # 3. Restore to the new target
        run_restore(
            backup_file=zip_path,
            target_gemini_dir=new_gemini,
            create_safety_point=True,
            rebuild_index=True,
            force=True,
            quiet=True,
        )

        # 4. Verify restored files
        restored_conv_1 = new_gemini / "antigravity" / "conversations" / "convo_1.db"
        restored_conv_2 = new_gemini / "antigravity" / "conversations" / "convo_2.db"
        restored_transcript = (
            new_gemini / "antigravity" / "brain" / "casc-111" / ".system_generated" / "logs" / "transcript.jsonl"
        )
        restored_skill = new_gemini / "config" / "skills" / "my-skill" / "SKILL.md"
        restored_proto = new_gemini / "antigravity" / "agyhub_summaries_proto.pb"

        self.assertTrue(restored_conv_1.exists(), f"Missing: {restored_conv_1}")
        self.assertTrue(restored_conv_2.exists(), f"Missing: {restored_conv_2}")
        self.assertTrue(restored_transcript.exists(), f"Missing: {restored_transcript}")
        self.assertTrue(restored_skill.exists(), f"Missing: {restored_skill}")
        self.assertTrue(restored_proto.exists(), f"Missing: {restored_proto}")

        # Verify restored content matches original
        self.assertEqual(
            restored_skill.read_text(encoding="utf-8"),
            (self.mock_config / "SKILL.md").read_text(encoding="utf-8"),
        )

        # 5. Verify index rebuilding worked
        self.assertGreater(restored_proto.stat().st_size, 0)

    def test_cli_subcommands(self):
        """Verifies CLI execution for backup, list, inspect, and verify."""
        script_path = pathlib.Path(__file__).parent / "antigravity_backup.py"
        test_backup_dir = self.test_path / "cli_backups"

        # 1. Test backup via CLI
        cmd_backup = [
            sys.executable,
            str(script_path),
            "backup",
            "--src",
            str(self.mock_gemini),
            "--dest",
            str(test_backup_dir),
            "--tag",
            "cli_test",
            "--force",
        ]
        res = subprocess.run(cmd_backup, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"CLI backup failed: {res.stderr}")
        self.assertIn("Backup completed successfully", res.stdout)

        # 2. Test list via CLI
        cmd_list = [sys.executable, str(script_path), "list", "--dest", str(test_backup_dir)]
        res = subprocess.run(cmd_list, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("antigravity_backup_", res.stdout)

        # 3. Test inspect via CLI
        backup_files = list(test_backup_dir.glob("*.zip"))
        self.assertEqual(len(backup_files), 1)
        backup_file = backup_files[0]

        cmd_inspect = [sys.executable, str(script_path), "inspect", "--file", str(backup_file)]
        res = subprocess.run(cmd_inspect, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("Discovered Components", res.stdout)
        self.assertIn("Total Conversations : 2", res.stdout)

        # 4. Test verify via CLI
        cmd_verify = [sys.executable, str(script_path), "verify", "--file", str(backup_file)]
        res = subprocess.run(cmd_verify, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("Integrity Check PASSED", res.stdout)


if __name__ == "__main__":
    unittest.main()

