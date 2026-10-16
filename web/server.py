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
    """Gracefully terminates any running ChatGPT desktop instances on macOS or Windows."""
    if IS_WINDOWS:
        try:
            subprocess.run(["taskkill", "/IM", "ChatGPT.exe"], capture_output=True)
            subprocess.run(["taskkill", "/IM", "Codex.exe"], capture_output=True)
        except Exception:
            pass
    else:
        try:
            subprocess.run(["osascript", "-e", 'quit app "ChatGPT"'], capture_output=True, timeout=2)
        except Exception:
            pass
    
    time.sleep(0.5)
    
    info = get_running_chatgpt_info()
    if info["running"] and info["pid"]:
        try:
            os.kill(info["pid"], 15 if not IS_WINDOWS else 9)
            time.sleep(1)
        except Exception:
            pass
            
    info = get_running_chatgpt_info()
    if info["running"] and info["pid"]:
        try:
            os.kill(info["pid"], 9)
            time.sleep(0.5)
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
            shutil.rmtree(link_path)
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
    Updates the default profile symlink and ~/.codex/auth.json so that opening
    ChatGPT from Dashboard, Dock, Taskbar, or Spotlight ALWAYS uses this active account.
    """
    stop_chatgpt()
    time.sleep(0.5)

    profile_parent = PRIMARY_PROFILE_LINK.parent
    if account_id in ["primary", "default"]:
        target_profile = profile_parent / "Codex-primary"
        target_auth = HOME / ".codex-primary" / "auth.json"
    else:
        target_profile = profile_parent / f"Codex-{account_id}"
        target_auth = HOME / f".codex-{account_id}" / "auth.json"

    # 1. Preserve original profile if it's a real directory
    if not (PRIMARY_PROFILE_LINK.is_symlink() or os.path.islink(PRIMARY_PROFILE_LINK)) and PRIMARY_PROFILE_LINK.exists():
        primary_dest = profile_parent / "Codex-primary"
        if not primary_dest.exists():
            shutil.copytree(PRIMARY_PROFILE_LINK, primary_dest)
        primary_auth = HOME / ".codex-primary" / "auth.json"
        if not primary_auth.exists() and (PRIMARY_HOME / "auth.json").exists():
            primary_auth.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PRIMARY_HOME / "auth.json", primary_auth)

    # 2. Update directory link (Symlink on macOS, Junction on Windows)
    link_profile_directory(PRIMARY_PROFILE_LINK, target_profile)

    # 3. Update ~/.codex/auth.json
    if target_auth.exists():
        PRIMARY_HOME.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_auth, PRIMARY_HOME / "auth.json")

    # Clear stale profile singletons
    for rel in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        lock_file = target_profile / rel
        if lock_file.exists() or lock_file.is_symlink():
            try:
                lock_file.unlink()
            except Exception:
                pass

    # 4. Launch ChatGPT natively
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
                
                # Clean up directories
                shutil.rmtree(HOME / f".codex-{account_id}", ignore_errors=True)
                shutil.rmtree(PRIMARY_PROFILE_LINK.parent / f"Codex-{account_id}", ignore_errors=True)

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
