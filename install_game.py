import sys
import json
import zipfile
import shutil
import urllib.request
import urllib.error
import tempfile
import getpass
import re
from pathlib import Path
from urllib.parse import urlparse

STEAM_PATH = Path(r"C:\Program Files (x86)\Steam")
# These destinations are configured on first launch and saved locally.
PATHS_SETTINGS_FILE = Path(__file__).parent / "paths_settings.json"
DEPOTCACHE = STEAM_PATH / "depotcache"
LUA_DIR = STEAM_PATH / "config" / "stplug-in"
HISTORY_FILE = Path(__file__).parent / "install_history.json"
HUBCAP_SETTINGS_FILE = Path(__file__).parent / "hubcap_settings.json"
HUBCAP_API_BASE = "https://hubcapmanifest.com/api/v1"
RYUU_SETTINGS_FILE = Path(__file__).parent / "ryuu_settings.json"
RYUU_API_BASE = "https://generator.ryuu.lol/api"



def extract_app_id(value: str) -> str:
    """Accept a numeric Steam App ID or extract one from a Steam Store URL."""
    value = value.strip().strip('"').strip("'")
    if value.isdigit():
        return value

    candidate = value if "://" in value else "https://" + value
    try:
        parsed = urlparse(candidate)
        match = re.search(r"/app/(\d+)(?:/|$)", parsed.path, re.IGNORECASE)
        if match and parsed.hostname and (
            parsed.hostname == "steampowered.com"
            or parsed.hostname.endswith(".steampowered.com")
        ):
            return match.group(1)
    except Exception:
        pass
    return ""


def get_game_name(app_id: str) -> str:
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&filters=basic"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode())
        if data[app_id]["success"]:
            return data[app_id]["data"]["name"]
    except Exception:
        pass
    return None



def configure_install_paths(edit=False):
    """Load install destinations, prompting on first startup or when requested."""
    global LUA_DIR, DEPOTCACHE

    defaults = {
        "lua_dir": str(STEAM_PATH / "config" / "stplug-in"),
        "manifest_dir": str(STEAM_PATH / "depotcache"),
    }

    settings = {}
    if PATHS_SETTINGS_FILE.exists():
        try:
            settings = json.loads(PATHS_SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print("WARNING: Could not read saved path settings.")

    current_lua = settings.get("lua_dir") or defaults["lua_dir"]
    current_manifest = settings.get("manifest_dir") or defaults["manifest_dir"]

    if edit or not settings.get("lua_dir") or not settings.get("manifest_dir"):
        if edit:
            print("\n=== Change install folders ===")
            print("Press Enter to keep the current folder. Enter a new folder to change it.\n")
        else:
            print("\n=== First-time setup ===")
            print("Enter the folders where the installer should place downloaded files.")
            print("Press Enter to use the default Steam folders shown below.\n")

        lua_prompt = current_lua if edit else defaults["lua_dir"]
        manifest_prompt = current_manifest if edit else defaults["manifest_dir"]
        lua_input = input(f"Folder for .lua files [{lua_prompt}]: ").strip().strip('"')
        manifest_input = input(f"Folder for .manifest files [{manifest_prompt}]: ").strip().strip('"')

        settings = {
            "lua_dir": (lua_input or current_lua) if edit else (lua_input or defaults["lua_dir"]),
            "manifest_dir": (manifest_input or current_manifest) if edit else (manifest_input or defaults["manifest_dir"]),
        }

    try:
        lua_dir = Path(settings["lua_dir"]).expanduser()
        manifest_dir = Path(settings["manifest_dir"]).expanduser()
        lua_dir.mkdir(parents=True, exist_ok=True)
        manifest_dir.mkdir(parents=True, exist_ok=True)

        LUA_DIR = lua_dir
        DEPOTCACHE = manifest_dir
        PATHS_SETTINGS_FILE.write_text(
            json.dumps({"lua_dir": str(LUA_DIR), "manifest_dir": str(DEPOTCACHE)}, indent=2),
            encoding="utf-8",
        )
        print(f"\nLua files will be installed to: {LUA_DIR}")
        print(f"Manifest files will be installed to: {DEPOTCACHE}\n")
        return True
    except (OSError, KeyError, TypeError) as e:
        print(f"ERROR: Could not configure install folders: {e}")
        print("Check the folder paths and try again.\n")
        return False


def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_history(history: dict):
    HISTORY_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")



def load_hubcap_key() -> str:
    """Load the locally saved Hubcap API key, if one has been configured."""
    try:
        settings = json.loads(HUBCAP_SETTINGS_FILE.read_text(encoding="utf-8"))
        return settings.get("api_key", "").strip()
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""


def set_hubcap_key() -> bool:
    """Prompt for and save a Hubcap API key locally."""
    key = getpass.getpass("Enter your Hubcap API key (input hidden): ").strip()
    if not key:
        print("No key entered; existing setting was not changed.\n")
        return False

    try:
        HUBCAP_SETTINGS_FILE.write_text(
            json.dumps({"api_key": key}, indent=2), encoding="utf-8"
        )
        print(f"Hubcap API key saved to: {HUBCAP_SETTINGS_FILE}\n")
        print("Keep this file private: it contains your API key.\n")
        return True
    except OSError as e:
        print(f"ERROR: Could not save API key: {e}\n")
        return False


def download_from_hubcap(app_id: str) -> bool:
    """Download Hubcap's ZIP bundle for an App ID and pass it to install()."""
    original_input = app_id.strip()
    app_id = extract_app_id(original_input)
    if not app_id:
        print("ERROR: Enter a numeric Steam App ID or a valid Steam Store game link.\n")
        return False
    if original_input != app_id:
        print(f"Extracted Steam App ID: {app_id}")

    api_key = load_hubcap_key()
    if not api_key:
        print("No Hubcap API key is configured.")
        if not set_hubcap_key():
            return False
        api_key = load_hubcap_key()

    url = f"{HUBCAP_API_BASE}/manifest/{app_id}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/zip, application/octet-stream, */*",
            "User-Agent": "Steam-Manifest-Installer/1.0",
        },
        method="GET",
    )

    print(f"\nRequesting manifests for App ID {app_id} from Hubcap...")
    temp_path = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
            content_type = response.headers.get("Content-Type", "")

        # Hubcap normally returns a ZIP bundle. Check the ZIP signature before
        # handing it to the existing installer, so API error pages aren't saved.
        if not payload.startswith(b"PK\x03\x04"):
            detail = payload[:1000].decode("utf-8", errors="replace").strip()
            if "json" in content_type.lower() or detail.startswith("{"):
                try:
                    detail = json.dumps(json.loads(detail), indent=2)
                except json.JSONDecodeError:
                    pass
            print("ERROR: Hubcap did not return a ZIP archive.")
            if detail:
                print(f"Hubcap response: {detail[:1000]}")
            print()
            return False

        with tempfile.NamedTemporaryFile(
            prefix=f"hubcap_{app_id}_", suffix=".zip", delete=False
        ) as temp_file:
            temp_file.write(payload)
            temp_path = Path(temp_file.name)

        print(f"Downloaded {len(payload):,} bytes. Installing files...\n")
        return install(temp_path)

    except urllib.error.HTTPError as e:
        body = e.read(1000).decode("utf-8", errors="replace").strip()
        if e.code in (401, 403):
            print("ERROR: Hubcap rejected the API key. Set it again with [k].")
        elif e.code == 402:
            print("ERROR: Hubcap API quota/plan limit reached.")
        elif e.code == 404:
            print(f"ERROR: Hubcap has no manifest bundle for App ID {app_id}.")
        else:
            print(f"ERROR: Hubcap returned HTTP {e.code}.")
        if body:
            print(f"Details: {body}")
        print()
        return False
    except Exception as e:
        print(f"ERROR: Hubcap download failed: {e}\n")
        return False
    finally:
        # install() removes the temporary ZIP after a successful installation.
        # Clean it up here as well if validation or installation failed.
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def load_ryuu_key() -> str:
    """Load the locally saved Ryuu API key."""
    try:
        settings = json.loads(RYUU_SETTINGS_FILE.read_text(encoding="utf-8"))
        return settings.get("api_key", "").strip()
    except (OSError, json.JSONDecodeError, AttributeError):
        return ""


def set_ryuu_key() -> bool:
    """Prompt for and save a Ryuu API key locally."""
    key = getpass.getpass("Enter your Ryuu API key (input hidden): ").strip()
    if not key:
        print("No key entered; existing setting was not changed.\n")
        return False

    try:
        RYUU_SETTINGS_FILE.write_text(
            json.dumps({"api_key": key}, indent=2), encoding="utf-8"
        )
        print(f"Ryuu API key saved to: {RYUU_SETTINGS_FILE}")
        print("Keep this file private: it contains your API key.\n")
        return True
    except OSError as e:
        print(f"ERROR: Could not save Ryuu API key: {e}\n")
        return False


def download_from_ryuu(app_id: str) -> bool:
    """Download the default ZIP bundle from Ryuu's Manifests and install it."""
    original_input = app_id.strip()
    app_id = extract_app_id(original_input)
    if not app_id:
        print("ERROR: Enter a numeric Steam App ID or a valid Steam Store game link.\n")
        return False
    if original_input != app_id:
        print(f"Extracted Steam App ID: {app_id}")

    api_key = load_ryuu_key()
    if not api_key:
        print("No Ryuu API key is configured.")
        if not set_ryuu_key():
            return False
        api_key = load_ryuu_key()

    # Omitting file_type requests the complete ZIP (Lua + manifest files).
    url = f"{RYUU_API_BASE}/download/{app_id}"
    request = urllib.request.Request(
        url,
        headers={
            "X-Auth-Key": api_key,
            "Accept": "application/zip, application/octet-stream, */*",
            "User-Agent": "Steam-Manifest-Installer/1.0",
        },
        method="GET",
    )

    print(f"\nRequesting ZIP bundle for App ID {app_id} from Ryuu's Manifests...")
    temp_path = None
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
            content_type = response.headers.get("Content-Type", "")

        # Reject HTML/JSON error responses instead of treating them as ZIP files.
        if not payload.startswith(b"PK\x03\x04"):
            detail = payload[:1000].decode("utf-8", errors="replace").strip()
            if "json" in content_type.lower() or detail.startswith("{"):
                try:
                    detail = json.dumps(json.loads(detail), indent=2)
                except json.JSONDecodeError:
                    pass
            print("ERROR: Ryuu did not return a ZIP archive.")
            if detail:
                print(f"Ryuu response: {detail[:1000]}")
            print()
            return False

        with tempfile.NamedTemporaryFile(
            prefix=f"ryuu_{app_id}_", suffix=".zip", delete=False
        ) as temp_file:
            temp_file.write(payload)
            temp_path = Path(temp_file.name)

        print(f"Downloaded {len(payload):,} bytes. Installing files...\n")
        return install(temp_path)

    except urllib.error.HTTPError as e:
        body = e.read(1000).decode("utf-8", errors="replace").strip()
        if e.code in (401, 403):
            print("ERROR: Ryuu rejected the API key. Set it again with option 4.")
        elif e.code == 404:
            print(f"ERROR: Ryuu has no downloadable ZIP for App ID {app_id}.")
        elif e.code == 429:
            print("ERROR: Ryuu download limit reached. Try again later.")
        else:
            print(f"ERROR: Ryuu returned HTTP {e.code}.")
        if body:
            print(f"Details: {body}")
        print()
        return False
    except Exception as e:
        print(f"ERROR: Ryuu download failed: {e}\n")
        return False
    finally:
        # install() deletes the temporary ZIP on success; clean it up on failure.
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def install(zip_path: Path):
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
    except zipfile.BadZipFile:
        print(f"ERROR: '{zip_path.name}' is not a valid zip file. Try again.\n")
        return False
    except Exception as e:
        print(f"ERROR: Could not open zip: {e}. Try again.\n")
        return False

    DEPOTCACHE.mkdir(parents=True, exist_ok=True)
    LUA_DIR.mkdir(parents=True, exist_ok=True)

    lua_copied = []
    manifests_copied = []
    app_id = None

    # Extract everything
    with zipfile.ZipFile(zip_path, "r") as z:
        for name in names:
            filename = Path(name).name
            if not filename:
                continue

            if filename.endswith(".lua"):
                stem = Path(filename).stem
                if stem.isdigit():
                    app_id = stem

                dest = LUA_DIR / filename

                try:
                    with z.open(name) as src:
                        with open(dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)

                    lua_copied.append(filename)

                except Exception as e:
                    print(f"  WARNING: Could not copy {filename}: {e}")

            elif filename.endswith(".manifest"):
                dest = DEPOTCACHE / filename

                try:
                    with z.open(name) as src:
                        with open(dest, "wb") as dst:
                            shutil.copyfileobj(src, dst)

                    manifests_copied.append(filename)

                    if app_id is None:
                        stem = Path(filename).stem
                        if "_" in stem:
                            first = stem.split("_")[0]
                            if first.isdigit():
                                app_id = first

                except Exception as e:
                    print(f"  WARNING: Could not copy {filename}: {e}")

    # ZIP FILE IS DEFINITELY CLOSED HERE

    if not lua_copied and not manifests_copied:
        print("  No .lua or .manifest files found in zip. Try again.\n")
        return False

    game_name = None
    if app_id:
        print(f"  Looking up App ID {app_id}...", end=" ", flush=True)
        game_name = get_game_name(app_id)
        print(game_name if game_name else "Name not found")

    label = game_name or app_id or "Unknown"

    print(f"\nInstalled: {label}")

    if lua_copied:
        print(f"  Lua -> {LUA_DIR}")
        for f in lua_copied:
            print(f"    {f}")

    if manifests_copied:
        print(f"  Manifests -> {DEPOTCACHE}")
        for f in manifests_copied:
            print(f"    {f}")

    if app_id:
        history = load_history()
        history[app_id] = {
            "name": game_name or "Unknown",
            "lua": lua_copied,
            "manifests": manifests_copied,
            "lua_dir": str(LUA_DIR),
            "manifest_dir": str(DEPOTCACHE),
        }
        save_history(history)

    # Delete the ZIP after successful install
    try:
        import os
        os.remove(zip_path)
        print(f"\nDeleted source zip: {zip_path}")
    except Exception as e:
        print(f"\nWARNING: Could not delete source zip: {e}")

    return True


def uninstall():
    """Stays in uninstall mode until the user enters 0 (or nothing is left)."""
    while True:
        history = load_history()
        if not history:
            print("  No install history found.\n")
            return

        print("\nInstalled games:")
        ids = list(history.keys())
        for i, app_id in enumerate(ids):
            entry = history[app_id]
            name = entry.get("name", "Unknown")
            print(f"  [{i+1}] {name} — {len(entry['lua'])} lua, {len(entry['manifests'])} manifests")

        choice = input("\nEnter number to uninstall (or 0 to go back): ").strip()
        if choice == "0":
            print("Back to main menu.\n")
            return
        if not choice.isdigit():
            print("Invalid choice.")
            continue

        idx = int(choice) - 1
        if idx < 0 or idx >= len(ids):
            print("Invalid choice.")
            continue

        app_id = ids[idx]
        entry = history[app_id]
        name = entry.get("name", "Unknown")
        removed = []
        missing = []

        game_lua_dir = Path(entry.get("lua_dir", str(LUA_DIR)))
        game_manifest_dir = Path(entry.get("manifest_dir", str(DEPOTCACHE)))

        for filename in entry.get("lua", []):
            path = game_lua_dir / filename
            if path.exists():
                path.unlink()
                removed.append(str(path))
            else:
                missing.append(str(path))

        for filename in entry.get("manifests", []):
            path = game_manifest_dir / filename
            if path.exists():
                path.unlink()
                removed.append(str(path))
            else:
                missing.append(str(path))

        del history[app_id]
        save_history(history)

        print(f"\nUninstalled {name}:")
        for f in removed:
            print(f"  Deleted: {f}")
        for f in missing:
            print(f"  Already missing: {f}")


def read_menu_choice() -> str:
    """Read a numbered menu choice; press Enter to confirm."""
    return input("\nChoose an option: ").strip()


def main():
    print("=== Steam Manifest Installer ===")

    if not configure_install_paths():
        input("Press Enter to exit...")
        return

    if len(sys.argv) >= 2:
        zip_path = Path(sys.argv[1].strip('"'))
        print(f"\nDetected zip: {zip_path.name}")
        install(zip_path)
        input("\nPress Enter to exit...")
        return

    while True:
        print("\n=== Main Menu ===")
        print("  [1] Download from Hubcap")
        print("  [2] Download from Ryuu's Manifests")
        print("  [3] Set/change Hubcap API key")
        print("  [4] Set/change Ryuu API key")
        print("  [5] Uninstall games")
        print("  [6] Install ZIP manually")
        print("  [7] Change install folders (.lua / .manifest)")
        print("  [0] Exit")
        choice = read_menu_choice()

        if choice == "0":
            break
        elif choice == "1":
            app_id = input("Enter Steam App ID or Steam Store link: ").strip()
            download_from_hubcap(app_id)
        elif choice == "2":
            app_id = input("Enter Steam App ID or Steam Store link: ").strip()
            download_from_ryuu(app_id)
        elif choice == "3":
            set_hubcap_key()
        elif choice == "4":
            set_ryuu_key()
        elif choice == "5":
            uninstall()
        elif choice == "6":
            raw_path = input("Drag a ZIP file here or enter its path: ").strip().strip('"')
            if raw_path:
                install(Path(raw_path))
        elif choice == "7":
            configure_install_paths(edit=True)
        else:
            print("Invalid choice. Press a number from 0 to 7.")

    print("Bye!")


if __name__ == "__main__":
    main()
