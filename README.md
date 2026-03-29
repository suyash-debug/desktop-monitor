# Desktop Monitor

An AI-powered desktop activity monitor for Windows. It silently tracks your computer usage and gives you intelligent summaries of what you worked on, when you were idle, and how productive your day was — all running **100% locally** with no data sent to the cloud.

## Features

- **AI Summaries** — Natural language summaries of your activity, powered by Ollama (llama3.2)
- **Idle & Session Detection** — Automatically detects when you were away and groups activity into sessions
- **History Browser** — Browse any previous day with a visual session timeline
- **Natural Language Search** — Ask things like *"what was I working on yesterday in VS Code?"*
- **Productivity Insights** — Focus time, context switching, top apps, peak hours
- **100% Local & Private** — No cloud, no accounts, everything stays on your machine

## Requirements

- Windows 10 / 11
- Python 3.11+
- [Ollama](https://ollama.com/download) (for AI summaries)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) *(optional, for screenshot text)*

## Installation

### Step 1 — Install prerequisites

1. **Python 3.11+** — Download from [python.org](https://python.org). ✅ Check *"Add Python to PATH"* during install.
2. **Ollama** — Download from [ollama.com/download](https://ollama.com/download) and install.

### Step 2 — Clone the repo

```bash
git clone https://github.com/suyash-debug/desktop-monitor.git
cd desktop-monitor
```

### Step 3 — Run setup

Double-click **`setup.bat`** — it will:
- Install all Python dependencies
- Pull the `llama3.2` AI model via Ollama
- Check for Tesseract OCR

### Step 4 — Start the monitor

Double-click **`start_monitor.bat`**

Then open your browser at **http://127.0.0.1:7001**

---

## Auto-start on Windows login

To have it start automatically when you log in:

1. Press `Win + R`, type `shell:startup`, press Enter
2. Copy `start_monitor.vbs` into that folder

---

## Dashboard Pages

| Page | Description |
|------|-------------|
| **Timeline** | Today's activity — screenshots, window events, live stats |
| **History** | Browse past days — session timeline, idle periods, daily summary |
| **Search** | Natural language search across all recorded activity |
| **Insights** | Productivity metrics — focus time, top apps, hourly breakdown |
| **Settings** | Configure the monitor, check Ollama status |

---

## Configuration

Edit `config.yaml` to customize:

```yaml
collectors:
  screenshot:
    interval_seconds: 60      # How often to take screenshots
    vision_enabled: false     # Set true to enable Qwen vision (needs 6GB VRAM)
  window_tracker:
    interval_seconds: 3       # How often to check active window

llm:
  text_model: "llama3.2"      # Ollama model for summaries
  summary_interval_minutes: 60

dashboard:
  port: 7001
```

---

## Privacy

All data is stored locally in `./data/`. Nothing is sent externally. To exclude sensitive apps:

```yaml
privacy:
  excluded_apps:
    - "KeePass"
    - "1Password"
  excluded_window_titles:
    - "*password*"
    - "*banking*"
```

---

## Tech Stack

- **Backend** — Python, FastAPI, aiosqlite
- **AI** — Ollama (llama3.2), optional Qwen2.5-VL for vision
- **Frontend** — Jinja2 templates, HTMX, Chart.js
- **Collectors** — mss (screenshots), pygetwindow, pynput (keystrokes), pyperclip
