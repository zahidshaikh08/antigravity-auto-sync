---
name: agy-history-sync
description: Exports, imports, migrates, or synchronizes Antigravity chat history across macOS, Windows, and Linux, and connects with Google Drive for automatic background backup.
---

# Antigravity History Sync Skill

This skill allows the agent to backup, export, import, or synchronize conversation history for Antigravity (IDE and Antigravity 2.0).

## 1. When to Use
Activate this skill when the user asks to:
- Export their conversations or chat history to a ZIP file.
- Import conversations from a backup file or another computer (Mac ↔ Windows ↔ Linux).
- Sync their chat history with Google Drive.
- Check their conversation stats or storage usage.
- Exclude a private or NDA conversation from cloud synchronization.

## 2. CLI Execution Instructions
The tool is located at `/Users/zahidshaikh/StudioProjects/antigravity-auto-sync/cli.py`.

### Exporting Chats
To export all conversations to a portable ZIP archive:
```bash
python3 /Users/zahidshaikh/StudioProjects/antigravity-auto-sync/cli.py export -o ~/Desktop/antigravity-backup.zip
```
To export only conversations matching a specific project:
```bash
python3 /Users/zahidshaikh/StudioProjects/antigravity-auto-sync/cli.py export --project "my-project" -o ~/Desktop/project-chats.zip
```

### Importing Chats
To import a backup ZIP archive into Antigravity with safe merging and automatic path remapping:
```bash
python3 /Users/zahidshaikh/StudioProjects/antigravity-auto-sync/cli.py import /path/to/antigravity-backup.zip
```

### Google Drive Sync
To check status or run an immediate two-way sync with Google Drive:
```bash
python3 /Users/zahidshaikh/StudioProjects/antigravity-auto-sync/cli.py sync
```

To list local conversations:
```bash
python3 /Users/zahidshaikh/StudioProjects/antigravity-auto-sync/cli.py list
```

## 3. Important User Guidance
- After importing conversations, always advise the user to **reload or restart Antigravity** so the IDE refreshes its in-memory conversation sidebar.
- Emphasize to the user that imports are **non-destructive**: existing conversations on the local machine are never overwritten or lost.
