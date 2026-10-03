#!/usr/bin/env python3
"""
Antigravity History Sync - Unified CLI & Interactive Wizard
Provides both:
1. Interactive friendly menu wizard when run without arguments (or double-clicked).
2. Scriptable subcommands and flags for automation and Antigravity chat skill integration.
"""

import os
import sys
import argparse
from pathlib import Path
from typing import Optional

# Ensure core package can be imported
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from core.engine import HistoryEngine, AntigravityPaths
from core.gdrive import GDriveSyncClient
from core.daemon import SyncCoordinator


def format_size(bytes_num: int) -> str:
    """Formats bytes into human readable MB/KB."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_num < 1024.0:
            return f"{bytes_num:.1f} {unit}"
        bytes_num /= 1024.0
    return f"{bytes_num:.1f} TB"


def ensure_gdrive_credentials(gdrive: GDriveSyncClient) -> bool:
    """Checks and prompts for Google OAuth client ID & secret if not yet configured."""
    if gdrive.has_valid_client_credentials():
        return True

    print("\n" + "=" * 68)
    print("  🔑 Google Drive OAuth 2.0 Credentials Setup")
    print("=" * 68)
    print("To sync with your personal Google Drive, Google requires an OAuth")
    print("Client ID (Desktop Application type) from Google Cloud Console.\n")
    print("Quick 1-Minute Setup Guide:")
    print(" 1. Open Google Cloud Console Credentials:")
    print("    https://console.cloud.google.com/apis/credentials")
    print(" 2. Enable Google Drive API (if not already enabled):")
    print("    https://console.cloud.google.com/apis/library/drive.googleapis.com")
    print(" 3. Click '+ CREATE CREDENTIALS' -> 'OAuth client ID'")
    print(" 4. Choose Application type: 'Desktop app' -> Name: 'Antigravity Sync'")
    print(" 5. Copy your Client ID and Client Secret (or download the JSON file).\n")
    print(" [1] Enter Client ID and Client Secret manually")
    print(" [2] Load from a downloaded client_secret_*.json file")
    print(" [0] Cancel")
    print("-" * 68)
    choice = input("Choice [1-2, default 1]: ").strip()

    if choice == "2":
        path_str = input("Path to downloaded JSON file: ").strip().strip('"').strip("'")
        if not path_str:
            return False
        if gdrive.import_credentials_from_json(Path(path_str)):
            print("✔ Credentials saved successfully!")
            return True
        else:
            print("[!] Invalid credentials file.")
            return False
    elif choice == "0":
        return False
    else:
        c_id = input("Enter Client ID: ").strip()
        c_sec = input("Enter Client Secret: ").strip()
        if not c_id or not c_sec:
            print("[!] Client ID and Secret cannot be empty.")
            return False
        gdrive.save_client_credentials(c_id, c_sec)
        print("✔ Credentials saved successfully to ~/.gemini/config/gdrive_credentials.json!")
        return True


def run_interactive_menu():
    """Runs the friendly interactive terminal wizard."""
    engine = HistoryEngine()
    gdrive = GDriveSyncClient()
    coordinator = SyncCoordinator(engine, gdrive)

    while True:
        print("\n" + "=" * 60)
        print("    🚀 Antigravity Chat History Sync & Migration Tool")
        print("=" * 60)

        convs = engine.list_conversations()
        gdrive_status = "Connected" if gdrive.is_authenticated() else "Not Connected"

        print(f" • Local Conversations: {len(convs)}")
        print(f" • Google Drive Status:  {gdrive_status}")
        print(f" • Storage Directory:    {engine.history_dir}")
        print("-" * 60)
        print(" [1] Export all chats to portable ZIP (Mac / Windows / Linux)")
        print(" [2] Export specific project or conversations to ZIP")
        print(" [3] Import backup ZIP archive into Antigravity")
        print(" [4] Connect Google Drive (Sign in with Google)")
        print(" [5] Sync now with Google Drive (Push / Pull)")
        print(" [6] Start Background Auto-Sync Daemon")
        print(" [7] Inspect conversation list & disk usage")
        print(" [8] Disconnect Google Drive (Logout)")
        print(" [0] Exit")
        print("=" * 60)

        choice = input("Select an option [0-8]: ").strip()

        if choice == "1":
            default_name = f"antigravity-backup-{len(convs)}-chats.zip"
            out_str = input(f"Enter output path [default: ~/Desktop/{default_name}]: ").strip()
            if not out_str:
                out_path = Path.home() / "Desktop" / default_name
            else:
                out_path = Path(out_str).expanduser()

            print(f"[*] Exporting {len(convs)} conversations...")
            res = engine.export_archive(out_path)
            if res["success"]:
                print(f"\n✔ Successfully exported {res['count']} conversations!")
                print(f"  Archive:  {res['archivePath']}")
                print(f"  File Size: {format_size(res['fileSize'])}")
            else:
                print(f"\n[!] Export failed: {res.get('error')}")

        elif choice == "2":
            proj = input("Enter project keyword to filter (e.g. 'realty_bazaar' or leave empty): ").strip()
            default_name = f"antigravity-filtered-chats.zip"
            out_path = Path.home() / "Desktop" / default_name
            print(f"[*] Exporting filtered conversations...")
            res = engine.export_archive(out_path, filter_project=proj if proj else None)
            if res["success"]:
                print(f"\n✔ Successfully exported {res['count']} conversations to {out_path}!")
            else:
                print(f"\n[!] Export failed: {res.get('error')}")

        elif choice == "3":
            in_str = input("Enter path to backup ZIP file to import: ").strip()
            if not in_str:
                print("[!] Path cannot be empty.")
                continue
            in_path = Path(in_str).expanduser()
            if not in_path.exists():
                print(f"[!] File not found: {in_path}")
                continue

            print("\nSelect collision strategy for chats that already exist locally:")
            print(" [1] Newer: Keep whichever has the newer timestamp (Recommended)")
            print(" [2] Overwrite: Replace existing local chats with archive version")
            print(" [3] Skip: Only import chats that don't exist locally")
            c_strat = input("Choice [1-3, default 1]: ").strip()
            strat_map = {"1": "newer", "2": "overwrite", "3": "skip"}
            strategy = strat_map.get(c_strat, "newer")

            print(f"[*] Importing from {in_path} (Strategy: {strategy})...")
            res = engine.import_archive(in_path, conflict_strategy=strategy)
            if res["success"]:
                print("\n✔ Import Completed Successfully!")
                print(f"  • Total Processed: {res['totalProcessed']}")
                print(f"  • New Imported:   {res['newImported']}")
                print(f"  • Updated:        {res['updated']}")
                print(f"  • Skipped:        {res['skipped']}")
                if res.get("safetyBackup"):
                    print(f"  • Safety Backup:  {res['safetyBackup']}")
                print("\n👉 Please reload or restart Antigravity to view your imported chats!")
            else:
                print(f"\n[!] Import failed: {res.get('error')}")

        elif choice == "4":
            if not ensure_gdrive_credentials(gdrive):
                print("\n[!] Setup cancelled. Credentials are required for Google Drive sync.")
                continue
            print("\n[*] Starting Google Drive login...")
            if gdrive.start_oauth_flow():
                print("\n✔ Successfully connected to Google Drive!")
            else:
                print("\n[!] Failed to connect to Google Drive.")

        elif choice == "5":
            if not gdrive.is_authenticated():
                print("\n[!] Google Drive is not connected. Please choose option [4] first.")
                continue
            print("\n[*] Running two-way synchronization with Google Drive...")
            res = coordinator.sync_cycle()
            if res["success"]:
                print(f"\n✔ Sync Complete!")
                print(f"  • Uploaded:   {res['uploaded']}")
                print(f"  • Downloaded: {res['downloaded']}")
                print(f"  • Last Synced: {res['lastSyncTime']}")
            else:
                print(f"\n[!] Sync error: {res.get('error')}")

        elif choice == "6":
            if not gdrive.is_authenticated():
                print("\n[!] Google Drive is not connected. Please choose option [4] first.")
                continue
            coordinator.start_daemon_watcher(interval_seconds=30)

        elif choice == "7":
            print(f"\n--- Local Conversations ({len(convs)}) ---")
            for i, c in enumerate(convs[:20], 1):
                mod = c['lastModifiedTime'][:19].replace('T', ' ') if c['lastModifiedTime'] else 'Unknown'
                print(f"{i:2d}. [{c['id'][:8]}] {c['summary'][:40]:<42} ({c['stepCount']} steps, {mod})")
            if len(convs) > 20:
                print(f"   ... and {len(convs) - 20} more conversations.")

        elif choice == "8":
            gdrive.logout()
            print("\n✔ Disconnected from Google Drive.")

        elif choice == "0":
            print("\nGoodbye!")
            break
        else:
            print("[!] Invalid option. Please choose [0-8].")


def build_cli_parser() -> argparse.ArgumentParser:
    """Builds the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Antigravity Chat History Sync & Cross-Platform Migration CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # export
    export_p = subparsers.add_parser("export", help="Export conversations to a portable ZIP file")
    export_p.add_argument("-o", "--output", help="Path to output ZIP file (default: ~/Desktop/antigravity-backup.zip)")
    export_p.add_argument("--project", help="Filter conversations by project or folder name")
    export_p.add_argument("--ids", help="Comma-separated conversation IDs to export")
    export_p.add_argument("--no-media", action="store_true", help="Exclude large uploaded images and audio")

    # import
    import_p = subparsers.add_parser("import", help="Import conversations from a ZIP archive")
    import_p.add_argument("archive", help="Path to ZIP archive to import")
    import_p.add_argument("--conflict", choices=["newer", "overwrite", "skip"], default="newer", help="Conflict strategy (default: newer)")
    import_p.add_argument("--remap", action="append", help="Custom path remap in format 'old_path=new_path'")

    # list
    list_p = subparsers.add_parser("list", help="List all local conversations and statistics")
    list_p.add_argument("-n", "--limit", type=int, default=30, help="Maximum conversations to display (default: 30)")

    # login / logout / sync / daemon
    login_p = subparsers.add_parser("login", help="Authenticate with Google Drive via browser OAuth")
    login_p.add_argument("--credentials", help="Path to downloaded client_secret_*.json")
    login_p.add_argument("--client-id", help="Google Cloud OAuth Client ID")
    login_p.add_argument("--client-secret", help="Google Cloud OAuth Client Secret")
    subparsers.add_parser("logout", help="Disconnect local machine from Google Drive")
    subparsers.add_parser("sync", help="Run an immediate bidirectional sync with Google Drive")
    
    daemon_p = subparsers.add_parser("daemon", help="Run the continuous background sync watcher")
    daemon_p.add_argument("--interval", type=int, default=30, help="Polling interval in seconds (default: 30)")

    return parser


def main():
    if len(sys.argv) == 1:
        # No arguments: launch friendly interactive wizard
        run_interactive_menu()
        return

    parser = build_cli_parser()
    args = parser.parse_args()

    engine = HistoryEngine()
    gdrive = GDriveSyncClient()
    coordinator = SyncCoordinator(engine, gdrive)

    if args.command == "export":
        out_path = Path(args.output).expanduser() if args.output else Path.home() / "Desktop" / "antigravity-backup.zip"
        conv_ids = [i.strip() for i in args.ids.split(",")] if args.ids else None
        res = engine.export_archive(
            out_path,
            conversation_ids=conv_ids,
            filter_project=args.project,
            include_media=not args.no_media
        )
        if res["success"]:
            print(f"✔ Exported {res['count']} conversations to {res['archivePath']} ({format_size(res['fileSize'])})")
        else:
            print(f"[!] Export failed: {res.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "import":
        custom_remaps = {}
        if args.remap:
            for r in args.remap:
                if "=" in r:
                    old_p, new_p = r.split("=", 1)
                    custom_remaps[old_p] = new_p

        res = engine.import_archive(Path(args.archive).expanduser(), conflict_strategy=args.conflict, custom_path_remaps=custom_remaps)
        if res["success"]:
            print(f"✔ Import complete: {res['newImported']} new, {res['updated']} updated, {res['skipped']} skipped.")
            if res.get("safetyBackup"):
                print(f"  Safety backup created: {res['safetyBackup']}")
        else:
            print(f"[!] Import failed: {res.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list":
        convs = engine.list_conversations()
        print(f"Found {len(convs)} conversations in {engine.history_dir}:\n")
        print(f"{'ID':<10} {'STEPS':<6} {'MODIFIED':<20} {'TITLE'}")
        print("-" * 75)
        for c in convs[:args.limit]:
            mod = c['lastModifiedTime'][:19].replace('T', ' ') if c['lastModifiedTime'] else 'Unknown'
            print(f"{c['id'][:8]:<10} {c['stepCount']:<6} {mod:<20} {c['summary'][:36]}")
        if len(convs) > args.limit:
            print(f"\n... and {len(convs) - args.limit} more conversations.")

    elif args.command == "login":
        if getattr(args, "credentials", None):
            if not gdrive.import_credentials_from_json(Path(args.credentials)):
                print("[!] Failed to import credentials from file.", file=sys.stderr)
                sys.exit(1)
        elif getattr(args, "client_id", None) and getattr(args, "client_secret", None):
            gdrive.save_client_credentials(args.client_id, args.client_secret)

        if not ensure_gdrive_credentials(gdrive):
            print("[!] Credentials required for Google Drive.", file=sys.stderr)
            sys.exit(1)

        if gdrive.start_oauth_flow():
            print("✔ Connected to Google Drive.")
        else:
            sys.exit(1)

    elif args.command == "logout":
        gdrive.logout()
        print("✔ Disconnected from Google Drive.")

    elif args.command == "sync":
        res = coordinator.sync_cycle()
        if res["success"]:
            print(f"✔ Synced: {res['uploaded']} uploaded, {res['downloaded']} downloaded.")
        else:
            print(f"[!] Sync error: {res.get('error')}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "daemon":
        coordinator.start_daemon_watcher(interval_seconds=args.interval)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
