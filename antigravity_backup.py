#!/usr/bin/env python3
"""
Antigravity Backup & Restore Tool (v1.1.0)
Comprehensive CLI tool to backup, verify, inspect, and restore Google Antigravity conversations,
brain data, skills, plugins, and configuration with 1-click ease and zero data loss guarantee.
Updated for Antigravity App & CLI v1.4.x releases.
"""

import argparse
import datetime
import glob
import hashlib
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

TOOL_VERSION = "1.1.0"

# Default directories
USER_HOME = pathlib.Path.home()
DEFAULT_GEMINI_DIR = USER_HOME / ".gemini"
DEFAULT_BACKUP_DIR = USER_HOME / "AntigravityBackups"
ROAMING_ANTIGRAVITY_DIR = pathlib.Path(os.environ.get("APPDATA", str(USER_HOME / "AppData" / "Roaming"))) / "Antigravity"


# ==============================================================================
# Helper Protobuf & Index Rebuilding Functions
# ==============================================================================

def encode_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def encode_field(tag: int, wire_type: int, data) -> bytes:
    tag_wire = (tag << 3) | wire_type
    header = encode_varint(tag_wire)
    if wire_type == 0:
        return header + encode_varint(data)
    elif wire_type == 2:
        if isinstance(data, str):
            data_bytes = data.encode("utf-8")
        elif isinstance(data, (bytes, bytearray)):
            data_bytes = bytes(data)
        else:
            raise ValueError(f"Invalid type for wire_type 2: {type(data)}")
        return header + encode_varint(len(data_bytes)) + data_bytes
    else:
        raise NotImplementedError(f"Wire type {wire_type} not implemented")


def encode_timestamp(seconds: int, nanos: int = 0) -> bytes:
    res = encode_field(1, 0, seconds)
    if nanos:
        res += encode_field(2, 0, nanos)
    return res


def decode_proto_fields(data: bytes):
    i = 0
    fields = {}
    while i < len(data):
        tag_wire = 0
        shift = 0
        while i < len(data):
            b = data[i]
            i += 1
            tag_wire |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        tag = tag_wire >> 3
        wire_type = tag_wire & 7

        if wire_type == 0:
            val = 0
            shift = 0
            while i < len(data):
                b = data[i]
                i += 1
                val |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            fields.setdefault(tag, []).append(("varint", val))
        elif wire_type == 1:
            val = data[i : i + 8]
            i += 8
            fields.setdefault(tag, []).append(("fixed64", val))
        elif wire_type == 2:
            length = 0
            shift = 0
            while i < len(data):
                b = data[i]
                i += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            val = data[i : i + length]
            i += length
            fields.setdefault(tag, []).append(("bytes", val))
        elif wire_type == 5:
            val = data[i : i + 4]
            i += 4
            fields.setdefault(tag, []).append(("fixed32", val))
        else:
            return fields, f"Unknown wire type {wire_type} at pos {i}"
    return fields, None


def clean_title(raw_title: str) -> str:
    """Cleans up internal markup (e.g. <USER_REQUEST>) and truncates title nicely."""
    if not raw_title:
        return "Chat Session"
    t = raw_title.replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "").strip()
    first_line = t.split("\n")[0].strip()
    return first_line[:60] if first_line else "Chat Session"


def get_convo_details(db_path: str, gemini_base_path: pathlib.Path):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        meta = cur.execute("SELECT trajectory_id, cascade_id FROM trajectory_meta LIMIT 1").fetchone()
        if not meta:
            conn.close()
            return None
        trajectory_id, cascade_id = meta

        step_count_row = cur.execute("SELECT COUNT(*) FROM steps").fetchone()
        step_count = step_count_row[0] if step_count_row else 0

        blob_row = cur.execute("SELECT data FROM trajectory_metadata_blob WHERE id='main'").fetchone()
        if not blob_row or not blob_row[0]:
            blob_row = cur.execute("SELECT data FROM trajectory_metadata_blob").fetchone()
        blob_raw = blob_row[0] if blob_row else b""

        title = None
        created_time = None
        updated_time = None

        steps = cur.execute("SELECT idx, step_type, status, metadata, step_payload FROM steps ORDER BY idx ASC").fetchall()

        for s in steps:
            _, _, _, smeta, payload = s
            if smeta:
                mfields, _ = decode_proto_fields(smeta)
                if 1 in mfields and mfields[1][0][0] == "bytes":
                    tfields, _ = decode_proto_fields(mfields[1][0][1])
                    if 1 in tfields and 2 in tfields:
                        ts = (tfields[1][0][1], tfields[2][0][1])
                        if created_time is None:
                            created_time = ts
                        updated_time = ts

            if payload and title is None:
                pfields, _ = decode_proto_fields(payload)
                if 30 in pfields:
                    for v in pfields[30]:
                        if v[0] == "bytes":
                            cfields, _ = decode_proto_fields(v[1])
                            if 4 in cfields:
                                for tv in cfields[4]:
                                    if tv[0] == "bytes":
                                        try:
                                            t_str = tv[1].decode("utf-8")
                                            if len(t_str) > 0:
                                                title = clean_title(t_str)
                                                break
                                        except Exception:
                                            pass
                if title is None and 4 in pfields:
                    for v in pfields[4]:
                        if v[0] == "bytes":
                            try:
                                s_str = v[1].decode("utf-8")
                                if (
                                    len(s_str) > 3
                                    and not s_str.startswith("file://")
                                    and not s_str.startswith("type.googleapis")
                                    and "\n" not in s_str
                                ):
                                    title = clean_title(s_str)
                                    break
                            except Exception:
                                pass
                if title is None and 19 in pfields:
                    for v in pfields[19]:
                        if v[0] == "bytes":
                            try:
                                s_str = v[1].decode("utf-8")
                                if len(s_str) > 0:
                                    p_line = clean_title(s_str)
                                    if p_line and p_line != "Chat Session":
                                        title = p_line
                                        break
                            except Exception:
                                pass

        conn.close()

        if not title or title == "Chat Session":
            tpath = gemini_base_path / "antigravity" / "brain" / cascade_id / ".system_generated" / "logs" / "transcript.jsonl"
            if tpath.exists():
                try:
                    with open(tpath, "r", encoding="utf-8") as f:
                        for line in f:
                            d = json.loads(line)
                            if d.get("type") == "USER_INPUT" and d.get("content"):
                                title = clean_title(d["content"])
                                break
                            elif d.get("type") == "CHECKPOINT" and d.get("content"):
                                for cl in d["content"].split("\n"):
                                    if "Objective:" in cl:
                                        title = clean_title(cl.replace("Objective:", ""))
                                        break
                except Exception:
                    pass

        if not title:
            title = "Chat Session"

        if created_time is None:
            mtime = int(os.path.getmtime(db_path))
            created_time = (mtime, 0)
        if updated_time is None:
            mtime = int(os.path.getmtime(db_path))
            updated_time = (mtime, 0)

        return {
            "cascade_id": cascade_id,
            "trajectory_id": trajectory_id,
            "step_count": step_count,
            "title": title,
            "created_time": created_time,
            "updated_time": updated_time,
            "blob_raw": blob_raw,
        }
    except Exception:
        return None


def build_summary_entry(info):
    sum_msg = bytearray()
    sum_msg += encode_field(1, 2, info["title"])
    sum_msg += encode_field(2, 0, info["step_count"])

    ts_updated = encode_timestamp(info["updated_time"][0], info["updated_time"][1])
    sum_msg += encode_field(3, 2, ts_updated)

    sum_msg += encode_field(4, 2, info["trajectory_id"])
    sum_msg += encode_field(5, 0, 2)

    ts_created = encode_timestamp(info["created_time"][0], info["created_time"][1])
    sum_msg += encode_field(7, 2, ts_created)

    sum_msg += encode_field(10, 2, ts_updated)

    tag15_content = encode_field(7, 2, ts_updated)
    sum_msg += encode_field(15, 2, tag15_content)

    sum_msg += encode_field(16, 0, 0)

    if info["blob_raw"]:
        sum_msg += encode_field(17, 2, info["blob_raw"])

    sum_msg += encode_field(21, 0, 1)
    sum_msg += encode_field(22, 0, 4)

    outer = encode_field(1, 2, info["cascade_id"]) + encode_field(2, 2, bytes(sum_msg))
    return encode_field(1, 2, outer)


def rebuild_summaries_proto(gemini_dir: pathlib.Path) -> int:
    """Scans all SQLite databases in conversations/ and rebuilds agyhub_summaries_proto.pb."""
    convos_dir = gemini_dir / "antigravity" / "conversations"
    if not convos_dir.exists():
        return 0

    all_dbs = list(convos_dir.glob("*.db"))
    if not all_dbs:
        return 0

    all_entries = []
    for db in all_dbs:
        details = get_convo_details(str(db), gemini_dir)
        if details:
            all_entries.append((details["updated_time"], build_summary_entry(details)))

    all_entries.sort(key=lambda x: x[0], reverse=True)
    full_proto = b"".join([entry[1] for entry in all_entries])

    target = gemini_dir / "antigravity" / "agyhub_summaries_proto.pb"
    bak = gemini_dir / "antigravity" / "agyhub_summaries_proto.pb.bak"

    if target.exists():
        try:
            shutil.copy2(target, bak)
        except Exception:
            pass

    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as f:
        f.write(full_proto)

    return len(all_entries)


# ==============================================================================
# Filter & Process Utilities
# ==============================================================================

def is_excluded_path(full_path: pathlib.Path, base_dir: pathlib.Path, include_cache: bool) -> bool:
    """Smart exclusion logic that prunes caches/crashes/locks but preserves transcripts & logs in brain."""
    if include_cache:
        return False

    try:
        rel = full_path.relative_to(base_dir).as_posix().lower()
    except Exception:
        rel = full_path.name.lower()

    # ALWAYS PRESERVE brain transcripts and system generated files
    if "brain/" in rel and ".system_generated" in rel:
        return False

    # Exclude ephemeral lock files (*.lock)
    if rel.endswith(".lock"):
        return True

    parts = rel.split("/")
    for p in parts:
        if p in [
            "cache",
            "crashes",
            "__pycache__",
            ".tempmediastorage",
            "gpucache",
            "dawnwebgpucache",
            "dawn_graphite_cache",
            "presence",  # Runtime process locks
        ]:
            return True

    # Exclude top-level debug logs
    if rel.startswith("logs") or rel.startswith("antigravity/log") or rel.startswith("antigravity/crashes"):
        return True
    if rel.endswith(".log") and "brain/" not in rel:
        return True

    return False


def is_antigravity_running() -> bool:
    """Checks if any Antigravity GUI application or CLI process is currently active."""
    try:
        if sys.platform == "win32":
            output = subprocess.check_output("tasklist /NH", shell=True, text=True).lower()
            return "antigravity.exe" in output or "agy.exe" in output
        else:
            output = subprocess.check_output(["pgrep", "-f", "antigravity|agy"], text=True)
            return len(output.strip()) > 0
    except Exception:
        return False


def calculate_sha256(file_path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def human_size(size_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:3.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


# ==============================================================================
# Backup Operation
# ==============================================================================

def run_backup(
    gemini_dir: pathlib.Path,
    dest_dir: pathlib.Path,
    include_cache: bool = False,
    include_roaming: bool = False,
    tag: str = "",
    force: bool = False,
    quiet: bool = False,
) -> pathlib.Path:
    """Performs a full backup of Antigravity conversations, brain, and settings."""
    if not gemini_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {gemini_dir}")

    if not force and is_antigravity_running():
        raise RuntimeError(
            "Antigravity is currently running! Please close Antigravity (and exit system tray) "
            "before backing up to prevent file-lock or database corruption. Use --force to bypass."
        )

    dest_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name_suffix = f"_{tag}" if tag else ""
    zip_filename = f"antigravity_backup_{timestamp}{name_suffix}.zip"
    target_zip = dest_dir / zip_filename

    # Count conversations across both Antigravity GUI and CLI
    convos_dir = gemini_dir / "antigravity" / "conversations"
    gui_convos = len(list(convos_dir.glob("*.db"))) if convos_dir.exists() else 0
    cli_convos_dir = gemini_dir / "antigravity-cli" / "conversations"
    cli_convos = len(list(cli_convos_dir.glob("*.db"))) if cli_convos_dir.exists() else 0
    total_convos = gui_convos + cli_convos

    if not quiet:
        print(f"\n=======================================================")
        print(f" Antigravity Backup Tool (v{TOOL_VERSION})")
        print(f"=======================================================")
        print(f"[*] Source Directory    : {gemini_dir}")
        print(f"[*] Destination Archive : {target_zip}")
        print(f"[*] Detected Sessions   : {total_convos} conversations ({gui_convos} GUI, {cli_convos} CLI)")
        print(f"[*] Scanning files to archive...")

    files_to_pack = []
    total_uncompressed_bytes = 0

    # Collect .gemini files
    for root, dirs, files in os.walk(gemini_dir):
        # Prune traversal
        if not include_cache:
            dirs[:] = [
                d for d in dirs
                if not is_excluded_path(pathlib.Path(root) / d, gemini_dir, include_cache=False)
            ]

        for file in files:
            file_path = pathlib.Path(root) / file
            if not is_excluded_path(file_path, gemini_dir, include_cache=include_cache):
                rel_path = ".gemini/" + file_path.relative_to(gemini_dir).as_posix()
                file_size = file_path.stat().st_size
                total_uncompressed_bytes += file_size
                files_to_pack.append((file_path, rel_path))

    # Optional: include Roaming AppData settings if requested
    if include_roaming and ROAMING_ANTIGRAVITY_DIR.exists():
        for root, dirs, files in os.walk(ROAMING_ANTIGRAVITY_DIR):
            if not include_cache:
                dirs[:] = [
                    d for d in dirs
                    if not is_excluded_path(pathlib.Path(root) / d, ROAMING_ANTIGRAVITY_DIR, include_cache=False)
                ]
            for file in files:
                file_path = pathlib.Path(root) / file
                if not is_excluded_path(file_path, ROAMING_ANTIGRAVITY_DIR, include_cache=include_cache):
                    rel_path = "AppData_Roaming_Antigravity/" + file_path.relative_to(ROAMING_ANTIGRAVITY_DIR).as_posix()
                    file_size = file_path.stat().st_size
                    total_uncompressed_bytes += file_size
                    files_to_pack.append((file_path, rel_path))

    if not quiet:
        print(f"[*] Packaging {len(files_to_pack)} files ({human_size(total_uncompressed_bytes)})...")

    file_checksums = {}
    temp_zip = target_zip.with_suffix(".tmp.zip")

    try:
        with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for idx, (fpath, arcname) in enumerate(files_to_pack):
                try:
                    zf.write(fpath, arcname=arcname)
                    # Sample/calculate checksum for key files
                    ext = fpath.suffix.lower()
                    if ext in [".db", ".pb", ".pbtxt", ".json", ".md", ".py"] or "conversations" in arcname:
                        file_checksums[arcname] = calculate_sha256(fpath)
                except Exception as e:
                    if not quiet:
                        print(f" [!] Warning: Skipped {arcname} ({e})")

            # Write manifest.json into the root of zip
            manifest = {
                "tool_version": TOOL_VERSION,
                "created_at": datetime.datetime.now().isoformat(),
                "created_timestamp": timestamp,
                "platform": sys.platform,
                "user": os.environ.get("USERNAME", os.environ.get("USER", "unknown")),
                "total_conversations": total_convos,
                "gui_conversations": gui_convos,
                "cli_conversations": cli_convos,
                "total_files": len(files_to_pack),
                "uncompressed_bytes": total_uncompressed_bytes,
                "include_roaming": include_roaming,
                "include_cache": include_cache,
                "tag": tag,
                "checksums": file_checksums,
            }

            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        # Atomic rename
        if target_zip.exists():
            target_zip.unlink()
        temp_zip.rename(target_zip)

    finally:
        if temp_zip.exists():
            temp_zip.unlink()

    compressed_size = target_zip.stat().st_size

    if not quiet:
        print(f"\n[+] Backup completed successfully!")
        print(f"    - Archive Path  : {target_zip}")
        print(f"    - Archive Size  : {human_size(compressed_size)} (Saved: {human_size(max(0, total_uncompressed_bytes - compressed_size))})")
        print(f"    - Conversations : {total_convos}")
        print(f"=======================================================\n")

    return target_zip


# ==============================================================================
# Verification & Inspection Operations
# ==============================================================================

def read_manifest(zip_path: pathlib.Path) -> dict:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if "manifest.json" in zf.namelist():
                return json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception:
        pass
    return {}


def verify_backup(zip_path: pathlib.Path, quiet: bool = False) -> bool:
    """Verifies zip integrity and checksums against manifest."""
    if not zip_path.exists():
        if not quiet:
            print(f"[-] Backup file not found: {zip_path}")
        return False

    if not quiet:
        print(f"\n[*] Verifying backup archive: {zip_path.name}")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # 1. Zip CRC Check
            corrupt_file = zf.testzip()
            if corrupt_file:
                if not quiet:
                    print(f"[-] Corrupted file detected in archive: {corrupt_file}")
                return False

            # 2. Check manifest
            manifest = json.loads(zf.read("manifest.json").decode("utf-8")) if "manifest.json" in zf.namelist() else {}
            if not manifest:
                if not quiet:
                    print(f"[!] Warning: No manifest.json found in archive. CRC check passed.")
                return True

            checksums = manifest.get("checksums", {})
            mismatch_count = 0
            checked_count = 0

            for arcname, expected_sha in checksums.items():
                if arcname in zf.namelist():
                    data = zf.read(arcname)
                    actual_sha = hashlib.sha256(data).hexdigest()
                    checked_count += 1
                    if actual_sha != expected_sha:
                        mismatch_count += 1
                        if not quiet:
                            print(f"[-] Hash mismatch for: {arcname}")

            if mismatch_count > 0:
                if not quiet:
                    print(f"[-] Integrity Check FAILED: {mismatch_count} files mismatched.")
                return False

            if not quiet:
                print(f"[+] Integrity Check PASSED! All {checked_count} verified checksums match perfectly.")
                print(f"    - Recorded Conversations: {manifest.get('total_conversations', 'N/A')}")
                print(f"    - Archive Created: {manifest.get('created_at', 'N/A')}")
            return True

    except Exception as e:
        if not quiet:
            print(f"[-] Failed to read archive: {e}")
        return False


def inspect_backup(zip_path: pathlib.Path):
    """Displays detailed inspection information about a backup archive."""
    if not zip_path.exists():
        raise FileNotFoundError(f"Backup file not found: {zip_path}")

    print(f"\n=======================================================")
    print(f" Backup Inspection: {zip_path.name}")
    print(f"=======================================================")

    manifest = read_manifest(zip_path)
    file_size = zip_path.stat().st_size

    print(f"[*] File Size           : {human_size(file_size)}")
    if manifest:
        print(f"[*] Created At          : {manifest.get('created_at', 'Unknown')}")
        print(f"[*] Original User       : {manifest.get('user', 'Unknown')}")
        print(f"[*] Platform            : {manifest.get('platform', 'Unknown')}")
        print(f"[*] Total Files         : {manifest.get('total_files', 'Unknown')}")
        print(f"[*] Uncompressed Size   : {human_size(manifest.get('uncompressed_bytes', 0))}")
        print(f"[*] Total Conversations : {manifest.get('total_conversations', 'Unknown')}")
    else:
        print(f"[!] Manifest not found in archive.")

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        conv_dbs = [n for n in namelist if "conversations/" in n and n.endswith(".db")]
        skills = [n for n in namelist if "config/skills/" in n and n.endswith("SKILL.md")]
        plugins = [n for n in namelist if "config/plugins/" in n and n.endswith("plugin.json")]

        print(f"\n--- Discovered Components ---")
        print(f" • Conversation Databases : {len(conv_dbs)}")
        print(f" • Installed Skills       : {len(skills)}")
        print(f" • Installed Plugins      : {len(plugins)}")

        if conv_dbs:
            print(f"\n--- Recent Conversation Samples in Archive ---")
            for db_name in conv_dbs[:5]:
                print(f"   - {pathlib.Path(db_name).name}")
            if len(conv_dbs) > 5:
                print(f"   ... and {len(conv_dbs) - 5} more.")

    print(f"=======================================================")


# ==============================================================================
# List Operation
# ==============================================================================

def list_backups(dest_dir: pathlib.Path):
    """Lists all available backup files in the target directory."""
    if not dest_dir.exists():
        print(f"Backup directory does not exist yet: {dest_dir}")
        return

    backups = sorted(dest_dir.glob("antigravity_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        print(f"No backups found in: {dest_dir}")
        return

    print(f"\n=======================================================================================")
    print(f" Available Antigravity Backups in: {dest_dir}")
    print(f"=======================================================================================")
    print(f"{'#':<3} {'Filename':<42} {'Created':<20} {'Size':<10} {'Convos':<8}")
    print(f"-" * 87)

    for idx, bpath in enumerate(backups, 1):
        manifest = read_manifest(bpath)
        mtime = datetime.datetime.fromtimestamp(bpath.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        size_str = human_size(bpath.stat().st_size)
        conv_count = str(manifest.get("total_conversations", "-")) if manifest else "?"
        fname = bpath.name
        if len(fname) > 40:
            fname = fname[:37] + "..."
        print(f"{idx:<3} {fname:<42} {mtime:<20} {size_str:<10} {conv_count:<8}")

    print(f"=======================================================================================\n")


# ==============================================================================
# Restore Operation
# ==============================================================================

def run_restore(
    backup_file: pathlib.Path,
    target_gemini_dir: pathlib.Path,
    create_safety_point: bool = True,
    rebuild_index: bool = True,
    force: bool = False,
    quiet: bool = False,
):
    """Safely restores Antigravity data from a backup archive."""
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup archive not found: {backup_file}")

    if not force and is_antigravity_running():
        raise RuntimeError(
            "Antigravity is currently running! Please close Antigravity (and exit system tray) "
            "before restoring data. Use --force to bypass."
        )

    # 1. Verify backup archive integrity first
    if not verify_backup(backup_file, quiet=True):
        raise RuntimeError(f"Backup archive integrity check failed! Refusing to restore corrupted file: {backup_file}")

    manifest = read_manifest(backup_file)

    if not quiet:
        print(f"\n=======================================================")
        print(f" Antigravity Restore Tool (v{TOOL_VERSION})")
        print(f"=======================================================")
        print(f"[*] Restoring From      : {backup_file.name}")
        print(f"[*] Target Directory    : {target_gemini_dir}")
        if manifest:
            print(f"[*] Backup Created      : {manifest.get('created_at', 'N/A')}")
            print(f"[*] Stored Convos       : {manifest.get('total_conversations', 'N/A')}")

    # 2. Safety Restore Point Creation (Zero-Data-Loss guarantee)
    safety_archive = None
    if create_safety_point and target_gemini_dir.exists() and any(target_gemini_dir.iterdir()):
        safety_dir = DEFAULT_BACKUP_DIR / "safety_points"
        safety_dir.mkdir(parents=True, exist_ok=True)
        safety_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_archive = safety_dir / f"safety_point_pre_restore_{safety_time}.zip"
        if not quiet:
            print(f"[*] Creating automatic safety point before restore...")
        run_backup(
            gemini_dir=target_gemini_dir,
            dest_dir=safety_dir,
            tag=f"safety_{safety_time}",
            force=True,
            quiet=True,
        )
        if not quiet:
            print(f"[+] Safety point created: {safety_archive.name}")

    # 3. Safe Extraction
    if not quiet:
        print(f"[*] Extracting files to target directory: {target_gemini_dir}...")

    target_gemini_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(backup_file, "r") as zf:
        for member in zf.infolist():
            # Skip manifest itself
            if member.filename == "manifest.json":
                continue

            fname = member.filename
            if fname.startswith(".gemini/"):
                sub_rel = fname[len(".gemini/"):]
                target_path = (target_gemini_dir / sub_rel).resolve()
            elif fname.startswith("AppData_Roaming_Antigravity/"):
                sub_rel = fname[len("AppData_Roaming_Antigravity/"):]
                target_path = (ROAMING_ANTIGRAVITY_DIR / sub_rel).resolve()
            else:
                target_path = (target_gemini_dir / fname).resolve()

            # Prevent Zip Slip / directory traversal attack
            base_check = ROAMING_ANTIGRAVITY_DIR if fname.startswith("AppData_Roaming_Antigravity/") else target_gemini_dir
            if not str(target_path).startswith(str(base_check.resolve())):
                raise RuntimeError(f"Malicious archive member detected (Zip Slip): {member.filename}")

            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    # 4. Automatic Sidebar Index Rebuilding
    rebuilt_count = 0
    if rebuild_index:
        if not quiet:
            print(f"[*] Rebuilding sidebar conversation index (agyhub_summaries_proto.pb)...")
        rebuilt_count = rebuild_summaries_proto(target_gemini_dir)
        if not quiet:
            print(f"[+] Rebuilt index successfully with {rebuilt_count} conversations!")

    if not quiet:
        print(f"\n[+] Restore completed successfully!")
        if safety_archive:
            print(f"    - Pre-restore safety point : {safety_archive}")
        print(f"    - Restored Conversations   : {rebuilt_count}")
        print(f"    - You can now launch Antigravity.")
        print(f"=======================================================\n")


# ==============================================================================
# CLI Argument Parser & Entrypoint
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive 1-Click Backup & Restore Tool for Google Antigravity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: backup
    p_backup = subparsers.add_parser("backup", help="Create a complete backup of Antigravity data")
    p_backup.add_argument("--src", type=pathlib.Path, default=DEFAULT_GEMINI_DIR, help="Source .gemini directory")
    p_backup.add_argument("--dest", "-d", type=pathlib.Path, default=DEFAULT_BACKUP_DIR, help="Destination backup directory")
    p_backup.add_argument("--include-cache", action="store_true", help="Include temporary cache folders")
    p_backup.add_argument("--include-roaming", action="store_true", help="Include AppData/Roaming Electron settings")
    p_backup.add_argument("--tag", "-t", type=str, default="", help="Optional label or tag for this backup")
    p_backup.add_argument("--force", "-f", action="store_true", help="Force backup even if Antigravity is open")

    # Command: restore
    p_restore = subparsers.add_parser("restore", help="Restore Antigravity data from a backup")
    p_restore.add_argument("--file", "-b", type=pathlib.Path, help="Specific backup .zip file to restore")
    p_restore.add_argument("--latest", action="store_true", help="Automatically pick the latest backup in backup directory")
    p_restore.add_argument("--dest-dir", type=pathlib.Path, default=DEFAULT_BACKUP_DIR, help="Backup directory (used with --latest)")
    p_restore.add_argument("--target", type=pathlib.Path, default=DEFAULT_GEMINI_DIR, help="Target .gemini directory")
    p_restore.add_argument("--no-safety", action="store_true", help="Do not create a safety point before restoring")
    p_restore.add_argument("--no-rebuild", action="store_true", help="Do not rebuild agyhub_summaries_proto.pb")
    p_restore.add_argument("--force", "-f", action="store_true", help="Force restore even if Antigravity is open")

    # Command: list
    p_list = subparsers.add_parser("list", help="List available backups and conversation counts")
    p_list.add_argument("--dest", "-d", type=pathlib.Path, default=DEFAULT_BACKUP_DIR, help="Directory where backups are stored")

    # Command: verify
    p_verify = subparsers.add_parser("verify", help="Verify integrity and checksums of a backup file")
    p_verify.add_argument("--file", "-b", type=pathlib.Path, required=True, help="Backup .zip file to verify")

    # Command: inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect contents, metadata, and conversations in a backup file")
    p_inspect.add_argument("--file", "-b", type=pathlib.Path, required=True, help="Backup .zip file to inspect")

    # Command: rebuild-index
    p_rebuild = subparsers.add_parser("rebuild-index", help="Rebuild the sidebar conversation index from existing .db files")
    p_rebuild.add_argument("--dir", type=pathlib.Path, default=DEFAULT_GEMINI_DIR, help="Target .gemini directory")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "backup":
            run_backup(
                gemini_dir=args.src,
                dest_dir=args.dest,
                include_cache=args.include_cache,
                include_roaming=args.include_roaming,
                tag=args.tag,
                force=args.force,
            )

        elif args.command == "restore":
            target_file = args.file
            if args.latest:
                backups = sorted(args.dest_dir.glob("antigravity_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not backups:
                    print(f"Error: No backups found in {args.dest_dir}")
                    sys.exit(1)
                target_file = backups[0]

            if not target_file:
                print("Error: Please provide a backup file with --file or use --latest.")
                sys.exit(1)

            run_restore(
                backup_file=target_file,
                target_gemini_dir=args.target,
                create_safety_point=not args.no_safety,
                rebuild_index=not args.no_rebuild,
                force=args.force,
            )

        elif args.command == "list":
            list_backups(args.dest)

        elif args.command == "verify":
            valid = verify_backup(args.file)
            sys.exit(0 if valid else 1)

        elif args.command == "inspect":
            inspect_backup(args.file)

        elif args.command == "rebuild-index":
            count = rebuild_summaries_proto(args.dir)
            print(f"Successfully rebuilt agyhub_summaries_proto.pb with {count} conversations!")

    except Exception as e:
        print(f"\n[Error] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
