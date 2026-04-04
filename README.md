# LegionnAIre

> A network penetration testing framework with a modern Flask web UI and integrated AI-powered host analysis.

![LegionnAIre main interface](gifs/shots/hero_full.png)

---

## Why I built this

I've always liked Legion. The classic layout with hosts on the left, tabbed detail panels on the right, and a live process list at the bottom.  I think it is an excellent UX for a pentest workflow. But the PyQt6 desktop app was hard to develop with: it required a full Qt environment, X11 forwarding when working remotely, and a brittle dependency stack that seemed to break with Kali updates.

Since the main branch was moving to Flask, I rewrote the classic interface as a Flask web app. The layout is very close to the original. The keyboard shortcuts, tab structure, and process model are the same. The underlying Python scanning engine (`controller.py`, `logic.py`, the SQLAlchemy ORM, the staged nmap pipeline) is unchanged — I just replaced every Qt widget with its HTML equivalent, polled with a 1.5-second snapshot API instead of Qt signals, and ran the whole thing in a browser.

While I was in there I added the things I'd always wanted: Interactive terminals, AI host analysis via Claude (Vertex AI), tool keyword match highlighting with navigation arrows, better note taking, parallel nmap stages, a config GUI so you don't have to hand-edit `legion.conf`, and several other UI features. There is a full selenium test suite for developers.  The name **LegionnAIre** reflects the AI addition and its Legion roots.

---

## Features

### Core scanning
- **Parallel staged nmap** — stages 1–5 (port ranges) run simultaneously; stage 6 (NSE/vulners) runs after all stages finish against every discovered open port
- **45 tools auto-scheduled** on service discovery — feroxbuster, gobuster, nuclei, netexec, enum4linux-ng, ssh-audit, testssl, and more
- **Live output streaming** — output appears in real time as tools run; progress % for nmap via `--stats-every 5s`
- **Keyword match highlighting** — set search terms in Settings; matching lines turn orange in tool output; ▲/▼ arrows navigate between hits

![Services and ports panel](gifs/shots/services_annotated.png)

### Web interface
- Runs in any browser at `http://127.0.0.1:PORT` — works locally or over SSH port forwarding with no X11 needed
- Layout identical to the original Legion desktop app: host list left, tabbed panels right, process list bottom
- **All splitters draggable** with saved position; **font size controls** for upper and lower panels independently
- **Sticky process table header**, scrollable tab bar, context menus that stay in viewport
- Opens Firefox automatically on start with a dedicated isolated profile

![Process output with ANSI colour](gifs/shots/output_annotated.png)

### AI host analysis (Claude via Vertex AI)
- **Phase 1 — Synthesizer**: reads all tool output, NSE scripts, CVEs, and analyst notes for a host; extracts a structured findings table (severity-coded Critical/High/Medium/Low/Info)
- **Phase 2 — Attack Planner**: on-demand; takes Phase 1 findings as input and produces a specific, actionable attack plan with exact commands
- **Persistent history DB** at `~/.local/share/legion/ai_history.db` — analyses survive project switches; Jaccard similarity matching shows historical hosts that look like the current target (≥95% match on port/service/version fingerprint)
- Auth via Google ADC (`gcloud auth application-default login`) — no API key stored anywhere

![AI tab — Phase 1 findings table and Phase 2 attack plan](gifs/shots/ai_annotated.png)

### Interactive terminals (xterm.js)

Right-click any host → **Open Terminal** to get a full PTY session embedded directly in the browser — no SSH client, no separate window. The terminal runs inside an xterm.js panel in the bottom output area alongside your tool processes.

![xterm.js interactive terminal — full ANSI colour, live PTY session](gifs/shots/xterm_terminal.png)

- **Full PTY** — readline, tab completion, colour, cursor movement, scrollback all work exactly as in a real terminal
- **ANSI colour preserved** — the Kali bash prompt, `ls` colour coding, tool output highlights all render correctly
- **Ctrl+B to capture** — select any output in the terminal, press Ctrl+B, and it lands in the host's Notes tab with colour intact
- **Saved on project close** — terminal history is written to the project database so it survives save/open cycles
- **Multiple sessions** — each Interactive process gets its own tab in the upper output panel; click between them without losing state
- **Font size controls** — A−/A+ buttons resize the terminal font independently of other output panels

### Config manager (F2) — Easy Edit mode

Press **F2** to open the Config Manager. Click **⊞ Easy Edit** to switch from the raw conf textarea to a structured form editor — no need to know the `legion.conf` syntax.

![Easy Edit — structured form editor for all legion.conf sections](gifs/shots/easy_mode_dialog.png)

Easy Edit covers every section of the config in typed, labeled forms:

| Tab | What you can change |
|---|---|
| **General** | Max concurrent processes, process timeout, scheduler on/off, tool duplication mode |
| **Brute** | Hydra defaults — username, password, wordlist paths, per-service field visibility |
| **Tool** | Binary paths for nmap, hydra, and other tools |
| **StagedNmap** | Port ranges for each of the 6 scan stages (PORTS|spec or NSE|scripts) |
| **Host / Port / PortTerminal** | Searchable tables — add, edit, or remove host actions and port right-click menu entries with `[IP]`/`[PORT]` placeholder validation |
| **Scheduler** | Which tools fire automatically on service discovery, and for which service names |
| **Match** | Tag chip editor — add or remove keywords that get highlighted in tool output |

- **← Back to Advanced** applies your Easy Edit changes and returns to the raw textarea
- **✓ Apply to Config** serialises the form state into the raw conf without leaving Easy Edit
- Every save is timestamped to `~/.local/share/legion/backup/` — nothing is lost

### Notes
- **Ctrl+B** — copies the current terminal or DOM output selection into the host's Notes tab with ANSI colour preserved
- Notes render with full ANSI-to-HTML conversion; the Log tab also renders colour codes
- All nmap stage commands are written to Notes automatically so scans are reproducible

![Notes panel with Ctrl+B capture](gifs/shots/notes_annotated.png)

### CVEs and vulnerability data
- Vulners NSE runs as the final nmap stage against all discovered ports
- CVEs displayed per host with severity, description, and CVSS score
- NSE script output (smb-vuln-*, ssl-heartbleed, http-shellshock, etc.) stored per port in the Scripts tab

![CVEs panel](gifs/shots/cves_annotated.png)

### Brute force
- Hydra wired to the Brute tab — username, password, wordlist fields pre-fill from `legion.conf` defaults
- Combo file support (`-C` flag) for credential pair lists
- Per-service show/hide for username/password fields (`no-username-services`, `no-password-services` in conf)

### Project management
- SQLite database per session (WAL mode) — no shared state between instances
- Save / Save As / Open with full fidelity — screenshots, outputfile paths, keyword matches, interactive terminal history all persist correctly
- Heartbeat watchdog (20-second timeout) — cleans up gracefully when the browser closes

---

## Requirements

- **OS**: Kali Linux (recommended) or Ubuntu 20.04+
- **Python**: 3.10+
- **Browser**: Firefox (opened automatically; geckodriver required for Selenium tests)
- **Tools**: nmap, hydra, feroxbuster, gobuster, nuclei, netexec, enum4linux-ng, ssh-audit, testssl, and others

Install all tools at once:
```bash
sudo bash install_tools.sh
```

For AI analysis:
```bash
pip install "anthropic[vertex]"
gcloud auth application-default login
```

---

## Installation

```bash
git clone https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion
pip install -r requirements.txt
```

---

## Quick start

```bash
# Start the server (opens Firefox automatically)
sudo python3 legion.py --web

# Custom port
sudo python3 legion.py --web --port 8080

# Without auto-browser
sudo python3 legion.py --web --no-browser
```

Navigate to `http://127.0.0.1:5000` (or your chosen port).

1. **Add a host** — type an IP, CIDR, or hostname in the Add Hosts dialog; click Staged Scan
2. **Watch the scan** — five nmap stages run in parallel; the process list shows live progress %; vulners runs last
3. **Review results** — Services, Ports, Scripts, CVEs, and Notes tabs populate as data arrives
4. **Configure** — press F2 to open the Config Manager; use Easy Edit to add tools or adjust settings without touching the raw conf file
5. **Analyze with AI** — click the AI tab on any host; click Analyze when all scans finish

![Add host dialog — IP, CIDR, or hostname; Easy/Hard mode; timing slider](gifs/shots/add_host_dialog.png)

---

## Configuration

The main config file is at `~/.local/share/legion/legion.conf` (created on first run from the repo default).

Edit via the in-app Config Manager (F2 → Easy Edit) or directly:
```bash
sudoedit /root/.local/share/legion/legion.conf
```

Key sections:

| Section | Purpose |
|---|---|
| `[GeneralSettings]` | Max concurrent processes, scheduler toggle, process timeout |
| `[StagedNmapSettings]` | Port ranges per stage (stages 1–5 PORTS, stage 6 NSE) |
| `[SchedulerSettings]` | Tools that auto-run on service discovery |
| `[PortActions]` | Right-click menu tools for ports |
| `[HostActions]` | Right-click menu tools for hosts |
| `[BruteSettings]` | Hydra defaults, wordlist paths |
| `[ToolSettings]` | Binary paths (nmap, hydra, etc.) |
| `[MatchSettings]` | Keywords highlighted in tool output |

---

## Test suite

```bash
# Minimum before every commit
sudo python3 tests/test_behavioral.py

# Full offline suite (unit + Selenium)
sudo bash run_tests.sh

# With live target (Metasploitable at given IP)
sudo bash run_tests.sh 192.168.85.11

# Specific suites
sudo bash run_tests.sh --unit
sudo bash run_tests.sh --selenium
sudo bash run_tests.sh --stories
```

Tests require geckodriver:
```bash
sudo apt install firefox-esr
wget https://github.com/mozilla/geckodriver/releases/latest/download/geckodriver-v0.35.0-linux64.tar.gz
tar xf geckodriver-v0.35.0-linux64.tar.gz && sudo mv geckodriver /usr/bin/
```

---

## Architecture

```
Browser  ──HTTP──►  Flask (legion.py --web)
                        │
                    app/web/routes.py        ← all API endpoints
                        │
                    controller/web_controller.py   ← Qt-free engine
                        │
              ┌─────────┴──────────┐
              │                    │
    controller/controller.py   db/SqliteDbAdapter.py
    (original Qt6 — unmodified)    (SQLAlchemy ORM, WAL mode)
```

The Flask layer wraps the original Qt6 controller with zero changes to the scanning logic:

| Qt6 | Flask equivalent |
|---|---|
| `QProcess.start(cmd)` | `subprocess.Popen(cmd, shell=True)` |
| `QTimer.singleShot(ms, fn)` | `threading.Timer(ms/1000, fn).start()` |
| `QTableView` | HTML table, polled every 1.5s |
| Qt signals | JS polling `/api/snapshot` |
| `self.view.updateInterface()` | no-op (browser polls) |

---

## Attribution

- Fork of [GoVanguard/legion](https://github.com/GoVanguard/legion) by Shane Scott (ifly53e)
- Original Sparta Python 2.7 codebase by [SECFORCE](https://github.com/SECFORCE/sparta)
- Flask web UI, parallel staged nmap, AI integration, and all features described above by Tim McLean (ifly53e, ThereAreSomeWhoCallMeTimAtViasat)
- nmap XML parsing engine originally by yunshu, modified by ketchup and SECFORCE
- Relies on nmap, hydra, SQLAlchemy, Flask, xterm.js, and many other open source tools

---

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE)
