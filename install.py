#!/usr/bin/env python3
"""
Antigravity History Sync - Automated Installer
Installs:
1. Antigravity Custom Skill into ~/.gemini/config/skills/agy-history-sync/
2. agy-sync system CLI command in user PATH (~/.local/bin or Windows equivalent)
3. One-click double-clickable launchers (.sh and .bat)
"""

import os
import sys
import shutil
from pathlib import Path


def install():
    src_dir = Path(__file__).parent.resolve()
    base_gemini = Path.home() / ".gemini"
    global_skills_dir = base_gemini / "config" / "skills" / "agy-history-sync"

    print("=" * 60)
    print("   Installing Antigravity History Sync & Google Drive Plugin")
    print("=" * 60)

    # 1. Install Custom Skill
    try:
        global_skills_dir.mkdir(parents=True, exist_ok=True)
        skill_src = src_dir / "skill" / "SKILL.md"
        skill_dest = global_skills_dir / "SKILL.md"
        if skill_src.exists():
            shutil.copy2(skill_src, skill_dest)
            print(f"✔ Installed Antigravity Skill: {skill_dest}")

        plugin_src = src_dir / "skill" / "plugin.json"
        plugin_dest = global_skills_dir / "plugin.json"
        if plugin_src.exists():
            shutil.copy2(plugin_src, plugin_dest)
            print(f"✔ Installed Plugin Manifest:  {plugin_dest}")

        # Copy core and cli into skill directory for standalone availability
        shutil.copy2(src_dir / "cli.py", global_skills_dir / "cli.py")
        core_dest = global_skills_dir / "core"
        if (src_dir / "core").exists():
            shutil.copytree(src_dir / "core", core_dest, dirs_exist_ok=True)
        print(f"✔ Bundled Engine Files in:    {global_skills_dir}")
    except Exception as e:
        print(f"[!] Note: Global skill directory access ({e}). Global skill can be registered via Antigravity.")

    # 2. Setup system CLI launcher
    if sys.platform != "win32":
        try:
            local_bin = Path.home() / ".local" / "bin"
            local_bin.mkdir(parents=True, exist_ok=True)
            launcher_file = local_bin / "agy-sync"
            script_content = f"""#!/bin/sh
exec python3 "{src_dir / 'cli.py'}" "$@"
"""
            with open(launcher_file, "w") as f:
                f.write(script_content)
            launcher_file.chmod(0o755)
            print(f"✔ Created CLI Executable:    {launcher_file}")
        except Exception as e:
            print(f"[!] Note: Could not write to ~/.local/bin ({e}).")
    else:
        win_bin = Path.home() / "AppData" / "Local" / "Microsoft" / "WindowsApps"
        launcher_file = win_bin / "agy-sync.bat"
        if win_bin.exists():
            with open(launcher_file, "w") as f:
                f.write(f'@python "{src_dir / "cli.py"}" %*\n')
            print(f"✔ Created Windows Launcher:  {launcher_file}")

    # 3. Create Desktop / Current Directory One-Click Launchers
    launchers_dir = src_dir / "launchers"
    launchers_dir.mkdir(parents=True, exist_ok=True)

    # Unix shell script
    with open(launchers_dir / "export_chats.sh", "w") as f:
        f.write(f'#!/bin/bash\npython3 "{src_dir / "cli.py"}" export\nread -p "Press Enter to exit..."\n')
    (launchers_dir / "export_chats.sh").chmod(0o755)

    with open(launchers_dir / "import_chats.sh", "w") as f:
        f.write(f'#!/bin/bash\npython3 "{src_dir / "cli.py"}"\n')
    (launchers_dir / "import_chats.sh").chmod(0o755)

    with open(launchers_dir / "sync_now.sh", "w") as f:
        f.write(f'#!/bin/bash\npython3 "{src_dir / "cli.py"}" sync\nread -p "Press Enter to exit..."\n')
    (launchers_dir / "sync_now.sh").chmod(0o755)

    # Windows batch script
    with open(launchers_dir / "export_chats.bat", "w") as f:
        f.write(f'@echo off\npython "{src_dir / "cli.py"}" export\npause\n')

    with open(launchers_dir / "import_chats.bat", "w") as f:
        f.write(f'@echo off\npython "{src_dir / "cli.py"}"\n')

    with open(launchers_dir / "sync_now.bat", "w") as f:
        f.write(f'@echo off\npython "{src_dir / "cli.py"}" sync\npause\n')

    print(f"✔ Generated One-Click Scripts in: {launchers_dir}")
    print("-" * 60)
    print("🎉 Installation Complete!")
    print("   • In terminal: Type 'agy-sync' for the interactive wizard")
    print("   • In Antigravity: Ask 'Sync my chats' or 'Export my history'")
    print("=" * 60)


if __name__ == "__main__":
    install()
