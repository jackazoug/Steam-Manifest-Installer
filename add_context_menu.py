import winreg
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent / "install_game.py"

def add():
    python = sys.executable
    command = f'"{python}" "{SCRIPT}" "%1"'

    key_path = r"Software\Classes\SystemFileAssociations\.zip\shell\InstallToSteam"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Install to Steam")
        winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, python)

    cmd_path = key_path + r"\command"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_path) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)

    print("Done! Right-click any .zip file and you'll see 'Install to Steam'.")

def remove():
    key_path = r"Software\Classes\SystemFileAssociations\.zip\shell\InstallToSteam"
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path + r"\command")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        print("Removed from context menu.")
    except FileNotFoundError:
        print("Not found in registry, nothing to remove.")

if __name__ == "__main__":
    print("Steam Manifest Installer - Context Menu Setup")
    print("  [1] Add to right-click menu")
    print("  [2] Remove from right-click menu")
    choice = input("\nChoice: ").strip()
    if choice == "1":
        add()
    elif choice == "2":
        remove()
    else:
        print("Invalid choice.")
    input("\nPress Enter to exit...")
