#!/usr/bin/env python3
import os
import sys
import json
import re
import time
import shutil
import base64
import subprocess
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

PORT = 5252
HOME = Path.home()
SCRIPT_DIR = Path(__file__).resolve().parent.parent
BASE_SHELL_SCRIPT = SCRIPT_DIR / "codex-multi-account.sh"
REGISTRY_DIR = HOME / ".codex-multi-account"
METADATA_FILE = REGISTRY_DIR / "metadata.json"
PRIMARY_HOME = HOME / ".codex"

# Platform detection
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

def get_platform_profile_link():
    """Returns the default profile directory path for the current OS."""
    if IS_WINDOWS:
        # Check Microsoft Store sandboxed package location first
        local_appdata = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
        packages_dir = local_appdata / "Packages"
        if packages_dir.exists():
            for p in packages_dir.glob("*Codex*"):
                store_profile = p / "LocalCache" / "Roaming" / "Codex"
                if store_profile.exists() or (p / "LocalCache").exists():
                    return store_profile
        # Default Roaming AppData for standalone installation
        roaming = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
        return roaming / "Codex"
    else:
        # macOS standard Application Support path
        return HOME / "Library" / "Application Support" / "Codex"

PRIMARY_PROFILE_LINK = get_platform_profile_link()

def load_metadata():
    if METADATA_FILE.exists():
        try:
            with open(METADATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_metadata(data):
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_jwt_details(auth_file_path):
    """Extracts real user name and email from auth.json JWT id_token without external APIs."""
    try:
        path = Path(auth_file_path)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        id_token = data.get("tokens", {}).get("id_token", "")
        if not id_token:
            return None
        payload = id_token.split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return {
            "name": claims.get("name") or claims.get("nickname") or "ChatGPT User",
            "email": claims.get("email") or "",
            "account_id": data.get("tokens", {}).get("account_id") or claims.get("sub", "")
        }
    except Exception:
        return None

def get_link_target(path):
    """Safely inspects a symlink or Windows directory junction target."""
    try:
        if path.is_symlink() or os.path.islink(path):
            return os.readlink(path)
    except Exception:
        pass
    return None

def get_active_account_id():
    """Determines currently active account by checking the active symlink/junction and auth.json."""
    # 1. Check symlink or junction target of primary profile link
    target = get_link_target(PRIMARY_PROFILE_LINK)
    if target:
        base = os.path.basename(str(target).rstrip('/\\'))
        if base.lower().startswith("codex-"):
            return base[6:].lower()

    # 2. Check active auth.json by comparing with saved profiles
    current_auth = PRIMARY_HOME / "auth.json"
    jwt_info = get_jwt_details(current_auth)
    if jwt_info and jwt_info.get("email"):
        current_email = jwt_info.get("email", "").lower()
        for p in HOME.glob(".codex-*"):
            if p.is_dir() and ".backup" not in p.name and ".bak" not in p.name:
                sub_jwt = get_jwt_details(p / "auth.json")
                if sub_jwt and sub_jwt.get("email", "").lower() == current_email:
                    return p.name[7:].lower()

    return "primary"

def get_running_chatgpt_info():
    """Detects if ChatGPT is running and which profile/account it is using across macOS and Windows."""
    running_pids = []
    active_account = None

    if IS_WINDOWS:
        try:
            # Query tasklist for ChatGPT.exe on Windows
            out = subprocess.check_output(["tasklist", "/FI", "IMAGENAME eq ChatGPT.exe", "/FO", "CSV", "/NH"], text=True)
            for line in out.splitlines():
                line = line.strip().strip('"')
                if line and ("chatgpt.exe" in line.lower() or "codex.exe" in line.lower()):
                    parts = [p.strip().strip('"') for p in line.split('","')]
                    if len(parts) >= 2:
                        try:
                            running_pids.append(int(parts[1]))
                        except ValueError:
                            pass
        except Exception:
            pass
        active_account = get_active_account_id()
    else:
        try:
            output = subprocess.check_output(["ps", "ax", "-o", "pid=", "-o", "command="], text=True)
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) < 2:
                    continue
                pid_str, cmd = parts[0], parts[1]
                
                if "ChatGPT.app/Contents/MacOS/ChatGPT" in cmd or "Codex.app/Contents/MacOS/Codex" in cmd:
                    if "--type=" in cmd:
                        continue
                    try:
                        pid = int(pid_str)
                        running_pids.append(pid)
                        
                        match = re.search(r'--user-data-dir=(.+?)(?=\s+--|\s*$)', cmd)
                        if match:
                            profile_path = match.group(1).rstrip('/')
                            profile_name = os.path.basename(profile_path)
                            if profile_name.lower() == "codex":
                                active_account = get_active_account_id()
                            elif profile_name.lower().startswith("codex-"):
                                active_account = profile_name[6:].lower()
                        else:
                            active_account = get_active_account_id()
                    except ValueError:
                        continue
        except Exception:
            pass

    if running_pids:
        return {"running": True, "active_account": active_account or get_active_account_id(), "pid": running_pids[0]}
    return {"running": False, "active_account": get_active_account_id(), "pid": None}

def list_all_accounts():
    status = get_running_chatgpt_info()
    active_id = status["active_account"] if status["running"] else get_active_account_id()
    meta = load_metadata()
    
    accounts = []
    
    # 1. Primary / Default account
    primary_home = HOME / ".codex-primary"
    primary_profile = PRIMARY_PROFILE_LINK.parent / "Codex-primary"
    
    primary_jwt = get_jwt_details(primary_home / "auth.json")
    if not primary_jwt and not (PRIMARY_PROFILE_LINK.is_symlink() or os.path.islink(PRIMARY_PROFILE_LINK)):
        primary_jwt = get_jwt_details(PRIMARY_HOME / "auth.json")
        
    primary_name = primary_jwt.get("name") if primary_jwt else meta.get("primary", {}).get("name", "Personal Account")
    primary_email = primary_jwt.get("email") if primary_jwt else ""

    accounts.append({
        "id": "primary",
        "name": primary_name,
        "email": primary_email,
        "label": meta.get("primary", {}).get("label", "Primary Account"),
        "home": str(primary_home if primary_home.exists() else PRIMARY_HOME),
        "profile": str(primary_profile if primary_profile.exists() else PRIMARY_PROFILE_LINK),
        "is_primary": True,
        "shared_history": True,
        "is_active": (active_id == "primary")
    })
    
    # 2. Secondary accounts
    found_accounts = {}
    
    instances_file = REGISTRY_DIR / "instances.tsv"
    if instances_file.exists():
        try:
            with open(instances_file, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 3:
                        acc_id, acc_home, acc_profile = parts[0], parts[1], parts[2]
                        if ".backup" not in acc_id and ".bak" not in acc_id and acc_id != "primary":
                            found_accounts[acc_id.lower()] = {
                                "home": acc_home,
                                "profile": acc_profile
                            }
        except Exception:
            pass

    for p in HOME.glob(".codex-*"):
        if p.is_dir() and p.name not in [".codex-multi-account", ".codex-primary"]:
            if ".backup" in p.name or ".bak" in p.name:
                continue
            acc_id = p.name[7:].lower()
            if acc_id not in found_accounts:
                profile_dir = PRIMARY_PROFILE_LINK.parent / f"Codex-{acc_id}"
                found_accounts[acc_id] = {
                    "home": str(p),
                    "profile": str(profile_dir)
                }

    for acc_id, paths in found_accounts.items():
        is_active = (active_id == acc_id)
        home_path = Path(paths["home"])
        sessions_path = home_path / "sessions"
        is_shared = sessions_path.is_symlink() or (sessions_path.exists() and PRIMARY_HOME.exists())
        
        jwt_info = get_jwt_details(home_path / "auth.json")
        email = jwt_info.get("email", "") if jwt_info else ""
        name = jwt_info.get("name", "") if jwt_info else meta.get(acc_id, {}).get("name", acc_id.title())
        label = meta.get(acc_id, {}).get("label") or acc_id.title()

        accounts.append({
            "id": acc_id,
            "name": name,
            "email": email,
            "label": label,
            "home": paths["home"],
            "profile": paths["profile"],
            "is_primary": False,
            "shared_history": True,
            "is_active": is_active
        })

    return accounts, status

def stop_chatgpt():
    """Gracefully terminates any running ChatGPT desktop instances on macOS or Windows, waiting for locks to release."""
    if IS_WINDOWS:
        try:
            subprocess.run(["taskkill", "/IM", "ChatGPT.exe"], capture_output=True)
            subprocess.run(["taskkill", "/IM", "Codex.exe"], capture_output=True)
        except Exception:
            pass
    else:
        try:
            subprocess.run(["osascript", "-e", 'quit app "ChatGPT"'], capture_output=True, timeout=3)
        except Exception:
            pass
    
    # Wait gracefully for up to 3 seconds for processes to flush cookies and state
    for _ in range(6):
        time.sleep(0.5)
        info = get_running_chatgpt_info()
        if not info["running"]:
            return
            
    info = get_running_chatgpt_info()
    if info["running"] and info["pid"]:
        try:
            os.kill(info["pid"], 15 if not IS_WINDOWS else 9)
            time.sleep(0.8)
        except Exception:
            pass
            
    info = get_running_chatgpt_info()
    if info["running"] and info["pid"]:
        try:
            os.kill(info["pid"], 9)
            time.sleep(0.5)
        except Exception:
            pass

def save_active_account_auth():
    """
    Saves the current ~/.codex/auth.json back to the active account profile directory.
    Prevents token expiry, stale session overwrites, and repeated OTP challenges.
    """
    current_auth = PRIMARY_HOME / "auth.json"
    if not current_auth.exists():
        return
    
    jwt_info = get_jwt_details(current_auth)
    current_email = (jwt_info.get("email") or "").lower() if jwt_info else ""
    current_sub = (jwt_info.get("account_id") or "").lower() if jwt_info else ""

    active_link_id = None
    target_link = get_link_target(PRIMARY_PROFILE_LINK)
    if target_link:
        base = os.path.basename(str(target_link).rstrip('/\\')).lower()
        if base.startswith("codex-"):
            active_link_id = base[6:]

    matched_id = None
    # 1. Match against known auth.json files by email or account ID
    p_jwt = get_jwt_details(HOME / ".codex-primary" / "auth.json")
    if p_jwt and current_email and (p_jwt.get("email", "").lower() == current_email):
        matched_id = "primary"
    
    if not matched_id and current_email:
        for p in HOME.glob(".codex-*"):
            if p.is_dir() and ".backup" not in p.name and ".bak" not in p.name and p.name != ".codex-multi-account":
                s_jwt = get_jwt_details(p / "auth.json")
                if s_jwt and (s_jwt.get("email", "").lower() == current_email):
                    matched_id = p.name[7:].lower()
                    break

    # 2. Check metadata registry against email prefix/keyword if unassigned
    if not matched_id and current_email:
        meta = load_metadata()
        for acc_id in meta:
            if acc_id.lower() in current_email or current_email.split('@')[0] in acc_id.lower():
                matched_id = acc_id.lower()
                break

    # 3. Fallback to active symlink target
    if not matched_id and active_link_id:
        matched_id = active_link_id
    
    save_id = matched_id or "primary"
    dest_dir = HOME / ".codex-primary" if save_id in ["primary", "default"] else HOME / f".codex-{save_id}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(current_auth, dest_dir / "auth.json")
    except Exception as e:
        print(f"Error saving active auth to {dest_dir}: {e}")

def sync_global_state_projects():
    """
    Ensures all local projects and workspaces are shared across all accounts.
    Merges project state in ~/.codex/.codex-global-state.json between root (active owner)
    and all inactive accounts, so switching accounts never hides projects in the sidebar.
    """
    global_state_path = PRIMARY_HOME / ".codex-global-state.json"
    if not global_state_path.exists():
        return
    try:
        with open(global_state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        ars = data.get("electron-account-renderer-state-v1", {})
        inactive = ars.get("inactive", {})
        
        # 1. Merge local-projects
        merged_projects = {}
        if isinstance(data.get("local-projects"), dict):
            merged_projects.update(data["local-projects"])
        for acc_key, acc_val in inactive.items():
            acc_globals = acc_val.get("globals", {})
            if isinstance(acc_globals.get("local-projects"), dict):
                merged_projects.update(acc_globals["local-projects"])
        
        if not merged_projects:
            return
        
        # 2. Merge project-order
        merged_order = []
        def add_order(order_list):
            if isinstance(order_list, list):
                for pid in order_list:
                    if pid in merged_projects and pid not in merged_order:
                        merged_order.append(pid)

        add_order(data.get("project-order"))
        for acc_key, acc_val in inactive.items():
            add_order(acc_val.get("globals", {}).get("project-order"))
        for pid in merged_projects:
            if pid not in merged_order:
                merged_order.append(pid)

        # 3. Merge project-appearances
        merged_appearances = {}
        if isinstance(data.get("project-appearances"), dict):
            merged_appearances.update(data["project-appearances"])
        for acc_key, acc_val in inactive.items():
            if isinstance(acc_val.get("globals", {}).get("project-appearances"), dict):
                merged_appearances.update(acc_val["globals"]["project-appearances"])

        # 4. Merge dictionary keys
        dict_keys = [
            "sidebar-project-thread-orders",
            "thread-project-assignments",
            "thread-project-membership-host-ids",
            "thread-writable-roots",
            "thread-workspace-root-hints",
            "thread-projectless-output-directories",
            "app-server-projects-migration-by-host",
            "app-server-project-id-by-legacy-project-id-by-host",
            "app-server-migrated-pinned-thread-ids-by-host",
            "queued-follow-ups"
        ]
        merged_dicts = {}
        for k in dict_keys:
            m = {}
            if isinstance(data.get(k), dict):
                m.update(data[k])
            for acc_key, acc_val in inactive.items():
                if isinstance(acc_val.get("globals", {}).get(k), dict):
                    m.update(acc_val["globals"][k])
            merged_dicts[k] = m

        # 5. Merge list keys
        list_keys = ["pinned-thread-ids", "projectless-thread-ids"]
        merged_lists = {}
        for k in list_keys:
            l = []
            if isinstance(data.get(k), list):
                for item in data[k]:
                    if item not in l:
                        l.append(item)
            for acc_key, acc_val in inactive.items():
                if isinstance(acc_val.get("globals", {}).get(k), list):
                    for item in acc_val["globals"][k]:
                        if item not in l:
                            l.append(item)
            merged_lists[k] = l

        # Apply merged project keys to root (active owner)
        data["local-projects"] = merged_projects
        data["project-order"] = merged_order
        data["project-appearances"] = merged_appearances
        for k, v in merged_dicts.items():
            if v:
                data[k] = v
        for k, v in merged_lists.items():
            if v:
                data[k] = v

        # Apply merged project keys to all inactive accounts
        for acc_key in inactive:
            inactive[acc_key].setdefault("globals", {})["local-projects"] = merged_projects
            inactive[acc_key]["globals"]["project-order"] = merged_order
            inactive[acc_key]["globals"]["project-appearances"] = merged_appearances
            for k, v in merged_dicts.items():
                if v:
                    inactive[acc_key]["globals"][k] = v
            for k, v in merged_lists.items():
                if v:
                    inactive[acc_key]["globals"][k] = v

        # Write atomically
        temp_file = global_state_path.with_name(f".{global_state_path.name}.tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_file.replace(global_state_path)
        shutil.copy2(global_state_path, global_state_path.with_suffix(".json.bak"))
    except Exception as e:
        print(f"Warning: Failed to sync global state projects: {e}")

def safe_rmtree(path):
    """Safely removes directory tree even if it contains read-only files or broken symlinks."""
    def handle_remove_readonly(func, p, exc_info):
        try:
            os.chmod(p, 0o777)
            func(p)
        except Exception:
            pass
    p = Path(path)
    if p.is_symlink() or os.path.islink(p):
        try:
            p.unlink()
        except Exception:
            pass
    elif p.exists():
        try:
            shutil.rmtree(p, onerror=handle_remove_readonly)
        except Exception:
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass

def link_profile_directory(link_path, target_path):
    """Links primary profile to target using POSIX symlinks on macOS or Directory Junctions on Windows."""
    target_path.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        if link_path.exists() or os.path.islink(link_path):
            try:
                subprocess.run(["cmd", "/c", "rmdir", str(link_path)], capture_output=True)
            except Exception:
                pass
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)], capture_output=True)
    else:
        if link_path.is_symlink():
            link_path.unlink()
        elif link_path.exists():
            safe_rmtree(link_path)
        link_path.symlink_to(target_path)

def launch_native_chatgpt():
    """Launches the official ChatGPT desktop application on macOS or Windows."""
    if IS_WINDOWS:
        try:
            os.startfile("chatgpt:")
        except Exception:
            subprocess.Popen(["cmd", "/c", "start", "chatgpt:"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(
            ["open", "-a", "/Applications/ChatGPT.app"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

def switch_to_account(account_id):
    """
    Sets the active account globally!
    1. Gracefully stops ChatGPT and waits for cookie/DB flush.
    2. Saves active tokens from ~/.codex/auth.json back to the active account folder.
    3. Synchronizes all projects across accounts in .codex-global-state.json.
    4. Updates the default profile symlink/junction.
    5. Restores target account's auth.json to ~/.codex/auth.json.
    6. Clears stale singleton locks and launches ChatGPT.
    """
    # 1. Gracefully stop ChatGPT and release locks
    stop_chatgpt()
    time.sleep(0.3)

    # 2. Save currently active account's tokens back before switching
    save_active_account_auth()

    # 3. Synchronize projects so both accounts see all projects in sidebar
    sync_global_state_projects()

    profile_parent = PRIMARY_PROFILE_LINK.parent
    if account_id in ["primary", "default"]:
        target_profile = profile_parent / "Codex-primary"
        target_auth = HOME / ".codex-primary" / "auth.json"
    else:
        target_profile = profile_parent / f"Codex-{account_id}"
        target_auth = HOME / f".codex-{account_id}" / "auth.json"

    # 4. Preserve original profile if it's a real directory
    if not (PRIMARY_PROFILE_LINK.is_symlink() or os.path.islink(PRIMARY_PROFILE_LINK)) and PRIMARY_PROFILE_LINK.exists():
        primary_dest = profile_parent / "Codex-primary"
        if not primary_dest.exists():
            shutil.copytree(PRIMARY_PROFILE_LINK, primary_dest)
        primary_auth = HOME / ".codex-primary" / "auth.json"
        if not primary_auth.exists() and (PRIMARY_HOME / "auth.json").exists():
            primary_auth.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PRIMARY_HOME / "auth.json", primary_auth)

    # 5. Update directory link (Symlink on macOS, Junction on Windows)
    link_profile_directory(PRIMARY_PROFILE_LINK, target_profile)

    # 6. Update ~/.codex/auth.json
    if target_auth.exists():
        PRIMARY_HOME.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_auth, PRIMARY_HOME / "auth.json")
    else:
        # Clean auth.json for newly created account so it starts fresh without inheriting previous account's token
        cur_auth = PRIMARY_HOME / "auth.json"
        if cur_auth.exists():
            try:
                cur_auth.unlink()
            except Exception:
                pass

    # Clear stale profile singletons
    for rel in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        lock_file = target_profile / rel
        if lock_file.exists() or lock_file.is_symlink():
            try:
                lock_file.unlink()
            except Exception:
                pass

    # 7. Launch ChatGPT natively
    launch_native_chatgpt()

class RequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            html_path = SCRIPT_DIR / "web" / "index.html"
            if html_path.exists():
                with open(html_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, "index.html not found")
        elif path == "/api/status":
            info = get_running_chatgpt_info()
            self._send_json(info)
        elif path == "/api/accounts":
            sync_global_state_projects()
            accounts, status = list_all_accounts()
            self._send_json({"accounts": accounts, "status": status})
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except Exception:
            payload = {}

        if path == "/api/switch":
            account_id = payload.get("account")
            if not account_id:
                self._send_json({"error": "Missing account id"}, status=400)
                return
            try:
                switch_to_account(account_id)
                time.sleep(1.5)
                accounts, status = list_all_accounts()
                self._send_json({"success": True, "active": account_id, "accounts": accounts, "status": status})
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)

        elif path == "/api/create":
            account_id = payload.get("id", "").strip().lower()
            name = payload.get("name", "").strip() or account_id.title()
            symlink_history = payload.get("symlink_history", True)

            if not account_id or not re.match(r'^[a-zA-Z0-9._-]+$', account_id):
                self._send_json({"error": "Invalid account ID. Use letters, numbers, dashes, and underscores only."}, status=400)
                return

            if account_id in ["primary", "default"]:
                self._send_json({"error": "Cannot use reserved identifier 'primary'"}, status=400)
                return

            try:
                meta = load_metadata()
                meta[account_id] = {"name": name, "label": name, "created_at": time.time()}
                save_metadata(meta)

                # Initialize profile directory
                target_home = HOME / f".codex-{account_id}"
                target_home.mkdir(parents=True, exist_ok=True)
                
                # Link local workspace (sessions, worktrees) if requested
                if symlink_history and PRIMARY_HOME.exists():
                    for folder in ["sessions", "archived_sessions", "attachments", "worktrees"]:
                        src = PRIMARY_HOME / folder
                        dst = target_home / folder
                        if src.exists() and not dst.exists():
                            src.mkdir(parents=True, exist_ok=True)
                            link_profile_directory(dst, src)

                # On macOS also run helper script if available
                if IS_MAC and BASE_SHELL_SCRIPT.exists():
                    args = [str(BASE_SHELL_SCRIPT), "--account", account_id, "--no-backup"]
                    if symlink_history:
                        args.append("--symlink-history")
                    subprocess.run(args, cwd=str(SCRIPT_DIR), capture_output=True, text=True)
                
                # Activate new account globally
                switch_to_account(account_id)
                time.sleep(1.5)

                accounts, status = list_all_accounts()
                self._send_json({"success": True, "account": account_id, "accounts": accounts, "status": status})
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)

        elif path == "/api/delete":
            account_id = payload.get("account")
            if not account_id or account_id in ["primary", "default"]:
                self._send_json({"error": "Cannot delete primary account"}, status=400)
                return
            
            try:
                active_id = get_active_account_id()
                if active_id == account_id:
                    switch_to_account("primary")
                    time.sleep(1)

                if IS_MAC and BASE_SHELL_SCRIPT.exists():
                    subprocess.run(
                        [str(BASE_SHELL_SCRIPT), "--reset", "--account", account_id],
                        cwd=str(SCRIPT_DIR),
                        capture_output=True,
                        text=True
                    )
                
                # Clean up directories safely
                safe_rmtree(HOME / f".codex-{account_id}")
                safe_rmtree(PRIMARY_PROFILE_LINK.parent / f"Codex-{account_id}")

                meta = load_metadata()
                if account_id in meta:
                    del meta[account_id]
                    save_metadata(meta)

                accounts, status = list_all_accounts()
                self._send_json({"success": True, "accounts": accounts, "status": status})
            except Exception as e:
                self._send_json({"error": str(e)}, status=500)

        elif path == "/api/quit":
            stop_chatgpt()
            time.sleep(0.5)
            self._send_json({"success": True, "status": get_running_chatgpt_info()})

        else:
            self.send_error(404, "Not Found")

def main():
    sync_global_state_projects()
    server = HTTPServer(("127.0.0.1", PORT), RequestHandler)
    platform_name = "Windows" if IS_WINDOWS else ("macOS" if IS_MAC else "Linux")
    print(f"ChatGPT Account Switcher running for {platform_name} at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()

if __name__ == "__main__":
    main()
