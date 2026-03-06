# Claude Drop

A lightweight native Ubuntu desktop app that lives in your system tray as a small **◆** icon. Click it and a chat panel slides up — no browser tab, no Electron app, no window in your taskbar.

![RAM usage ~12–20 MB](https://img.shields.io/badge/RAM-~15MB-green) ![Python 3](https://img.shields.io/badge/Python-3-blue) ![GTK3](https://img.shields.io/badge/GTK-3-blue)

## Why

Opening a browser just to ask Claude something breaks your flow. Claude Drop keeps it ambient — always one click away, always on top of whatever you're doing, then gone when you're done.

## How It Works

- Pure **Python 3 + GTK3** — the UI toolkit that GNOME itself uses
- **Zero npm/Electron/Chromium** — the whole app is one Python file
- RAM usage is roughly **12–20 MB** (vs 200+ MB for an Electron app)
- Shells out to the **Claude Code CLI** (`claude -p`) for completions — no API key needed
- Uses your existing **claude.ai OAuth session** from `~/.claude/.credentials.json`

## Prerequisites

- **Ubuntu** with GNOME desktop (22.04+)
- **Claude Code CLI** — `npm install -g @anthropic-ai/claude-code`
- Log in once: run `claude` in a terminal to authenticate

## Install

```bash
# Install the AppIndicator binding (one-time)
sudo apt install gir1.2-ayatanaappindicator3-0.1

# Enable the system tray extension (one-time)
gnome-extensions enable ubuntu-appindicators@ubuntu.com

# Clone and run
git clone https://github.com/tigran1997/claude-drop.git
cd claude-drop
python3 claude_drop.py
```

### Autostart on login

```bash
cp claude-drop.desktop ~/.config/autostart/
```

> **Note:** Edit the `Exec=` path in the `.desktop` file if you cloned to a different location.

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Enter` | Send message |
| `Shift+Enter` | New line in input |
| `Esc` | Hide panel |
| `Ctrl+K` | Clear conversation |
| `Ctrl+T` | New tab |
| `Ctrl+W` | Close tab |
| `Alt+1..9` | Switch to tab by number |
| `/clear` | Clear conversation (typed) |

## Features

- Full back-and-forth conversation with context
- **Tabs** — multiple independent conversations
- Code fence highlighting (``` blocks render in monospace orange)
- Draggable window (drag the header bar)
- Auto-detects auth errors and shows re-login prompt
- Progress bar pulses while waiting for a response
- Tab auto-titles from your first message

## Limitations

- No streaming — waits for the full reply (limitation of `claude -p`)
- No markdown rendering beyond code fences
- No file or image uploads
- History resets when you restart the app (no persistence to disk)
- Conversation context is prepended to each prompt (works but grows with history)

## Dependencies

| Dependency | Needed for | Pre-installed on Ubuntu GNOME? |
|---|---|---|
| Python 3 | App runtime | Yes |
| `python3-gi` (GTK3 bindings) | UI | Yes |
| `gir1.2-ayatanaappindicator3-0.1` | System tray icon | **No** — install manually |
| Node.js | Running Claude Code CLI | Depends |
| Claude Code CLI | Chat backend | **No** — `npm install -g @anthropic-ai/claude-code` |

## License

MIT
