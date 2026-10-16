<div align="center">

# ⚡ ChatGPT Account Switcher
### Seamless Multi-Account Profile Manager & OTP-Bypass Workflow for ChatGPT Desktop (macOS & Windows)

[![macOS Support](https://img.shields.io/badge/platform-macOS%2012%2B-black?style=flat&logo=apple)](https://www.apple.com/macos/)
[![Windows Support](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6?style=flat&logo=windows)](https://microsoft.com)
[![Python Standard Library](https://img.shields.io/badge/python-3.9%2B%20(zero%20deps)-blue?style=flat&logo=python)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![OpenAI Compatible](https://img.shields.io/badge/compatible-ChatGPT%20%7C%20Codex-10A37F?style=flat&logo=openai)](https://chatgpt.com)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/shafiquecbl/chatgpt-account-switcher/pulls)

**Switch between Personal, Work, and Client ChatGPT accounts on macOS and Windows with a single click — without logging out, without repeating 2FA/OTP, and while keeping all your local chats, projects, worktrees, and SQLite databases unified in one place.**

[Quick Start](#-quick-start) • [How It Works](#-how-it-works-technical-deep-dive) • [Features](#-key-features) • [FAQ](#-frequently-asked-questions-aeo) • [Architecture](#-architecture--directory-layout)

---

</div>

## 📌 Executive Summary (AIO & GEO Overview)

**ChatGPT Account Switcher** is an open-source cross-platform developer utility designed to solve the multi-account limitation of the official OpenAI ChatGPT Desktop App (formerly Codex Desktop) on **macOS** and **Windows**. 

Unlike standard web browsers that offer profile pickers, the ChatGPT Desktop application enforces a single active session. Logging out forces session termination, requiring a fresh OAuth flow and a One-Time Password (OTP/2FA) sent to an account manager or administrator. 

This tool introduces **isolated Chromium authentication environments** coupled with a **single unified local workspace** (`~/.codex` or `%USERPROFILE%\.codex`). Switching accounts takes under 1 second, persists all local SQLite conversation history, and natively syncs with macOS Dock, Windows Taskbar, and Start Menu launches.

---

## ⚡ The Problem vs. The Solution

| Challenge in Native ChatGPT App | Solution with ChatGPT Account Switcher |
|---|---|
| **Painful 2FA / OTP Loops:** Logging out invalidates local tokens, requiring manager OTP every time you switch accounts. | **Zero Repeated OTPs:** Sessions and OAuth refresh tokens persist in isolated profiles; OTP is required **only once** during initial onboarding. |
| **Data Fragmentation:** Workspaces or chats get isolated or lost across different profiles. | **Single Unified Workspace:** All local sessions, worktrees, attachments, and SQLite databases remain unified in `~/.codex` (`%USERPROFILE%\.codex`). |
| **Dock & Taskbar Disconnection:** External profile scripts break when you launch ChatGPT from the macOS Dock, Spotlight, or Windows Taskbar. | **Global System Sync:** Switching profiles re-points the default system profile (POSIX symlink on macOS, Directory Junction on Windows), making native launches open the active account. |
| **No Account Context:** Native app gives no visual clue of verified email or identity before launching. | **Auto-Decoded Credentials:** Web dashboard automatically extracts verified User Name and Email from OAuth JWT ID tokens without calling external APIs. |

---

## 🚀 Quick Start

### Prerequisites
- **macOS:** macOS 12 (Monterey) or later with Python 3.
- **Windows:** Windows 10 or 11 with Python 3 installed.
- Official **ChatGPT Desktop App** installed.

### Installation & Launch

1. **Clone the repository:**
   ```bash
   git clone https://github.com/shafiquecbl/chatgpt-account-switcher.git
   cd chatgpt-account-switcher
   ```

2. **Launch on macOS:**
   ```bash
   chmod +x ./start-switcher.sh ./codex-multi-account.sh
   ./start-switcher.sh
   ```
   *Or double-click `ChatGPT Switcher.command` on your Desktop.*

3. **Launch on Windows:**
   Double-click `start-switcher.bat` or run in Command Prompt / PowerShell:
   ```cmd
   start-switcher.bat
   ```

4. **Open Dashboard:**
   The dashboard automatically opens in your default browser at **`http://localhost:5252`**.

---

## 🛠️ How It Works (Technical Deep Dive)

ChatGPT Desktop on macOS is an Electron/Chromium hybrid application that relies on two distinct storage locations:
1. **Local State & Workspace (`~/.codex`)**: Contains project files, local chat sessions (`sessions/`), worktrees (`worktrees/`), shell snapshots, and SQLite databases (`state_5.sqlite`).
2. **Browser User Data (`~/Library/Application Support/Codex`)**: Contains Chromium session cookies, IndexedDB, and local storage holding the OAuth web session.

### The Switching Mechanism:
```
                               ┌──────────────────────────────────────────────┐
                               │       Unified Workspace (~/.codex)          │
                               │  (Chats, Projects, Worktrees, SQLite DBs)    │
                               └──────────────────────┬───────────────────────┘
                                                      │ (Shared via Symlinks)
                         ┌────────────────────────────┴───────────────────────────┐
                         ▼                                                        ▼
         ┌───────────────────────────────┐                        ┌───────────────────────────────┐
         │     Profile A (Personal)      │                        │       Profile B (Work)        │
         ├───────────────────────────────┤                        ├───────────────────────────────┤
         │ Auth: ~/.codex-primary        │                        │ Auth: ~/.codex-work           │
         │ Data: .../Codex-primary       │                        │ Data: .../Codex-work          │
         └───────────────┬───────────────┘                        └───────────────┬───────────────┘
                         │                                                        │
                         └─────────────────────────┬──────────────────────────────┘
                                                   │
                                     Active Selection in Dashboard
                                                   │
                                                   ▼
                               ┌──────────────────────────────────────┐
                               │  ~/Library/Application Support/Codex │
                               │        (Global System Symlink)       │
                               └───────────────────┬──────────────────┘
                                                   │
                                  ┌────────────────┴────────────────┐
                                  ▼                                 ▼
                         macOS Dock Launch                 Spotlight Search
```

1. **Profile Isolation**: Each secondary profile gets an isolated Chromium cache directory (e.g. `~/Library/Application Support/Codex-work`) and dedicated `auth.json`.
2. **Workspace Linking**: All local conversation logs and databases (`state_*.sqlite`) in `~/.codex` are shared across profiles using POSIX symlinks.
3. **Global System Activation**: When an account is switched in the dashboard, the system updates `~/Library/Application Support/Codex` as a symlink pointing to the designated account and synchronizes `~/.codex/auth.json`.
4. **Dock & Spotlight Parity**: Because the default macOS application path is symlinked, opening ChatGPT from the Dock or Spotlight automatically launches the chosen active account.

---

## 🎯 Key Features

- **Instant Account Switching**: Switch profiles in under 1 second without terminal commands.
- **Zero-Dependency Lightweight Backend**: Built completely with Python 3's native standard library (`http.server`, `urllib`, `subprocess`, `json`, `base64`).
- **Cryptographic JWT Credential Decoding**: Automatically decodes and displays the user's real name and verified email address directly from the OAuth `id_token` without calling external APIs.
- **Unified Local Projects & Chats**: Never lose project context or local sessions when hitting model rate limits.
- **Dock, Spotlight & Launchpad Native**: Operates seamlessly with native macOS application lifecycle.
- **Safe Profile Management**: Safeguards primary directories; resets and cleanup actions strictly protect system root and primary workspace paths.

---

## 📂 Architecture & Directory Layout

```
chatgpt-account-switcher/
├── start-switcher.sh       # Zero-config background daemon and browser launcher
├── codex-multi-account.sh  # Low-level POSIX profile engine & symlink orchestrator
├── web/
│   ├── server.py           # Native Python 3 REST API & status listener (Port 5252)
│   └── index.html          # Polished dark-mode responsive management interface
├── LICENSE                 # MIT License
└── README.md               # Technical documentation & usage guide
```

---

## ❓ Frequently Asked Questions (AEO & Search Answers)

### Can I switch ChatGPT accounts on Mac without logging out?
**Yes.** ChatGPT Account Switcher isolates login sessions in distinct profile directories while preserving authentication tokens. You can switch accounts via a local web dashboard without logging out or triggering OTP verification.

### Does this tool share my local chats and projects between accounts?
**Yes.** All local conversations, SQLite databases (`state_*.sqlite`), worktrees, and session history in `~/.codex` are linked across all configured profiles. Only OAuth authentication tokens remain isolated.

### Why does ChatGPT ask for OTP every time I switch accounts normally?
OpenAI's desktop application lacks a native multi-account profile switcher. Logging out wipes your session cookies and `auth.json`, forcing a full OAuth challenge with Two-Factor Authentication (2FA/OTP) on subsequent sign-ins.

### Does ChatGPT Account Switcher work if I launch the app from the macOS Dock?
**Yes.** The switcher updates macOS's default `~/Library/Application Support/Codex` path as a symbolic link pointing to the currently active profile. Opening ChatGPT from the Dock, Spotlight, or Launchpad opens whichever profile is currently active.

### Is this safe to use?
**Yes.** All authentication tokens and cookies remain entirely local on your machine. No telemetry, third-party tracking, or external servers are involved.

---

## 📄 Schema.org Structured Metadata (JSON-LD)

```json
{
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  "name": "ChatGPT Account Switcher",
  "operatingSystem": "macOS 12.0+",
  "applicationCategory": "DeveloperApplication",
  "offers": {
    "@type": "Offer",
    "price": "0",
    "priceCurrency": "USD"
  },
  "description": "Seamless multi-account profile manager and OTP bypass workflow for the ChatGPT Desktop App on macOS.",
  "softwareVersion": "2.0.0",
  "author": {
    "@type": "Person",
    "name": "Muhammad Shafique",
    "url": "https://github.com/shafiquecbl"
  }
}
```

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).
