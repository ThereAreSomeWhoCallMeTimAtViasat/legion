![LegionnAIre](images/LegionnaireBannerGood.png)

![LegionnAIre main interface](gifs/shots/hero_full.png)

---

## What is LegionnAIre?

LegionnAIre is an open source, semi-automated network penetration testing framework for discovery, reconnaissance, and exploitation. It is a fork of [Legion](https://github.com/GoVanguard/legion), which was itself a fork of [Sparta](https://github.com/SECFORCE/sparta) — a tool that has been in active pentest use since 2015.

The core workflow is the same as it has always been:

1. **Add targets** — IPs, CIDRs, hostnames, or ranges. Legion adds them to scope.
2. **Scan** — nmap runs staged port scans across your targets. Services are identified and versioned.
3. **Auto-attack** — the scheduler fires the right tool for each discovered service automatically. HTTP gets feroxbuster, nuclei, gobuster. SSH gets ssh-audit. SMB gets netexec and enum4linux-ng. And so on.
4. **Investigate** — browse results by host: open ports, service versions, CVEs, NSE script output, screenshots, and tool output all in one place.
5. **Exploit** — right-click any host or port for a context menu of targeted tools. Open an interactive terminal. Run Hydra against authentication services from the Brute tab.
6. **Document** — notes per host with Ctrl+B terminal capture, scan commands auto-logged, AI-generated attack plans.

### What the original Legion did — and still does

These are the foundational capabilities inherited from Sparta/Legion and fully preserved in this Flask rewrite:

- **Staged nmap scanning** — customizable port ranges scanned in sequence; each stage's results feed the next. Timing, fragmentation, host discovery, and custom options all configurable per scan.
- **Semi-automated tool scheduling** — `legion.conf` maps service names to tools. When nmap identifies a service, the matching tools run automatically without user intervention.
- **Rich context menus** — right-click any host or port for a list of relevant tools. Dozens of host actions (dnsrecon, masscan, theharvester) and port actions (nikto, wpscan, sslscan, sqlmap, and more) built in and fully customisable.
- **Multi-host scope management** — add individual IPs, CIDR subnets, ranges, or hostnames. Mark hosts as checked. Delete hosts from scope. Filter by OS, state, or service.
- **CPE and CVE detection** — Vulners NSE runs against every discovered service; CVEs are stored per host with severity and ExploitDB cross-references.
- **Integrated screenshotting** — EyeWitness captures web service screenshots automatically on HTTP/HTTPS discovery.
- **Hydra brute forcing** — the Brute tab targets FTP, SSH, MySQL, PostgreSQL, VNC, Telnet, and more with configurable wordlists.
- **nmap XML import** — import existing scan results without re-scanning. All parsed data (hosts, ports, services, scripts) loads into the project database.
- **IPv6 support** — full IPv6 scanning with automatic fallback when connectivity is unavailable.
- **Project save and restore** — SQLite-backed sessions save all results, notes, process history, screenshots, and tool output. Pick up exactly where you left off.
- **Extensible tool configuration** — `legion.conf` defines every host action, port action, and scheduled tool. Add your own scripts with `[IP]`, `[PORT]`, and `[OUTPUT]` placeholders. No code changes required.

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

| Requirement | Minimum | Notes |
|---|---|---|
| **OS** | Kali Linux 2024.1+ | Ubuntu 22.04+ also works; Kali has most tools pre-installed |
| **Python** | 3.10+ | 3.11–3.13 tested |
| **Firefox ESR** | any recent | Opened automatically by `--web`; geckodriver needed for Selenium tests |
| **sudo / root** | required | nmap, masscan, and several schedulers need raw socket access |
| **Go** | 1.20+ | Needed to install pd-httpx, katana, gau, waybackurls, nomore403, urlfinder |
| **Disk** | ~3 GB | Tools + Python packages + project databases + Go tool chain |

---

## Installation — Automated (recommended)

The automated installer handles everything in one step: Python packages, system tools, geckodriver, Firefox profile, and optional AI tab setup.

> **Important:** The Flask web UI lives on the `flask-clean` branch.
> The default `master` branch is the original upstream Qt5 desktop app.
> The `--branch flask-clean` flag below is **required** — without it you
> will clone the wrong codebase and `python3 legion.py --web` will not exist.

```bash
git clone --branch flask-clean https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion

# Confirm you are on the right branch before continuing
git branch        # should show: * flask-clean

sudo bash install.sh
```

**Options:**

| Flag | Effect |
|---|---|
| `--no-tools` | Skip system security tools (install Python packages only) |
| `--no-ai` | Skip the Vertex AI setup prompt |

---

## Installation — Manual (step by step)

Use this if you need to understand what each step does, skip certain parts, or troubleshoot a failed automated install.

### Step 1 — Clone the repository onto the correct branch

The repository has multiple branches. The Flask web UI is on **`flask-clean`**.
The default `master` branch is the original upstream Qt5 desktop app — it does
not have `--web` mode, `install.sh`, or `requirements.txt` in the correct state.

```bash
# --branch flask-clean is mandatory
git clone --branch flask-clean \
    https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion

# Verify you are on the right branch before doing anything else
git branch
# Output must show:   * flask-clean
# If it shows master or anything else, run:  git checkout flask-clean

git log --oneline -3
# Should show recent commits starting with "v10.1xx" version tags
```

### Step 2 — Install Python packages

`requirements.txt` covers **both** Flask web mode and Qt6 GUI mode.

```bash
sudo pip3 install --break-system-packages -r requirements.txt
```

Expected output: a list of packages being installed, ending with `Successfully installed ...`

**Verify:**
```bash
python3 -c "import flask, PyQt6.QtCore, sqlalchemy, anthropic; print('OK')"
# Expected: OK
```

If this fails, check:
- Python version: `python3 --version` must be 3.10+
- pip is available: `python3 -m pip --version`
- On Ubuntu you may need: `sudo apt-get install python3-pip python3-dev`

### Step 3 — Install system security tools

Kali Linux already includes most of the 50+ tools Legion uses (nmap, feroxbuster, netexec, eyewitness, hydra, enum4linux-ng, etc.).  This script installs the ones that are not in Kali's apt repos:

| Tool | Method | Purpose |
|---|---|---|
| pd-httpx | Go | HTTP technology detection |
| katana | Go | Web crawler |
| gau | Go | Passive URL collection |
| waybackurls | Go | Wayback Machine URL fetch |
| nomore403 | Go | 403 bypass checker |
| urlfinder | Go | URL extraction |
| kerbrute | GitHub binary | Kerberos user enum |
| rdp-sec-check | apt / GitHub | RDP security audit |
| jexboss | GitHub clone | JBoss vulnerability scanner |
| LeakSearch | GitHub clone | Credential leak search |
| nuclei templates | nuclei CLI | Template download for nuclei scans |

```bash
sudo bash install_tools.sh
```

Expected runtime: 2–10 minutes depending on network speed.

**Verify Go is installed first** — the script needs it:
```bash
go version          # should show go1.20 or later
# If not: sudo apt-get install golang-go
```

**Verify individual tools after install:**
```bash
for t in pd-httpx katana gau waybackurls nomore403 urlfinder kerbrute rdp-sec-check; do
    command -v $t && echo "✓ $t" || echo "✗ $t — missing"
done
```

### Step 4 — geckodriver (required for Selenium tests and screenshooter)

**On Kali:** geckodriver is already at `/usr/bin/geckodriver` — nothing to do.

**On Ubuntu:**
```bash
# Find the latest release at https://github.com/mozilla/geckodriver/releases
GECKODRIVER_VERSION="v0.35.0"
curl -fsSL "https://github.com/mozilla/geckodriver/releases/download/${GECKODRIVER_VERSION}/geckodriver-${GECKODRIVER_VERSION}-linux64.tar.gz" \
    | sudo tar xz -C /usr/local/bin
sudo chmod +x /usr/local/bin/geckodriver
geckodriver --version   # verify
```

### Step 5 — (Optional) AI tab — Vertex AI credentials

The AI tab uses Anthropic Claude via Google Cloud Vertex AI. Authentication uses
[Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) — no API key file is stored anywhere.

**Prerequisites:** a Google Cloud project with the Vertex AI API enabled.

```bash
# 1. Authenticate (one-time; already done if you use Claude Code daily)
gcloud auth application-default login

# 2. Tell Legion which project and region to use
#    Edit ~/.claude/settings.json (create it if it doesn't exist):
cat >> ~/.claude/settings.json << 'EOF'
{
  "ANTHROPIC_VERTEX_PROJECT_ID": "your-gcp-project-id",
  "CLOUD_ML_REGION": "global"
}
EOF
```

**Verify:**
```bash
python3 -c "
import json, pathlib
cfg = json.loads(pathlib.Path('~/.claude/settings.json').expanduser().read_text())
print('project:', cfg.get('ANTHROPIC_VERTEX_PROJECT_ID'))
print('region: ', cfg.get('CLOUD_ML_REGION'))
"
```

### Step 6 — Verify the complete install

Runs 93 tests that check every Python import, verify Legion starts in web mode, confirm Qt6 works, and check that every tool binary is in PATH:

```bash
sudo python3 -m pytest tests/test_requirements.py --noconftest -v
```

Expected output:
```
tests/test_requirements.py::test_shared_package_imports[flask-flask] PASSED
tests/test_requirements.py::test_flask_web_mode_starts_and_responds PASSED
tests/test_requirements.py::test_qt6_qapplication_offscreen PASSED
tests/test_requirements.py::test_kali_apt_tool_present[nmap] PASSED
...
93 passed in ~45s
```

If some tool binary tests fail, run `sudo bash install_tools.sh` and try again.

---

## Installation — Docker

Docker gives you Legion plus all tools in a self-contained image. Scanning still works — the container gets the same raw socket capabilities as the host via `--cap-add`.

### Option A — Docker Compose (easiest)

```bash
# --branch flask-clean is required (master is the Qt5 desktop app, not web)
git clone --branch flask-clean \
    https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion

# Build the image (takes 5–15 minutes; downloads all tools)
sudo docker compose build

# Start Legion in the background
sudo docker compose up -d

# Follow the logs
sudo docker compose logs -f

# Open in browser:  http://127.0.0.1:5000
```

**Stop:**
```bash
sudo docker compose down           # stop and remove container (keeps volumes)
sudo docker compose down -v        # also remove volumes (deletes saved projects)
```

**Custom port:**
```bash
LEGION_PORT=8080 sudo docker compose up -d
# Open http://127.0.0.1:8080
```

**Mount a host directory for project files:**
```bash
LEGION_PROJECTS_DIR=/home/kali/legion-projects sudo docker compose up -d
# Save/open .legion files from /home/kali/legion-projects inside the app
```

### Option B — Docker manual (full control)

```bash
# Build
sudo docker build -t legion .

# Run — attach to host network so scans reach LAN targets
sudo docker run -d \
  --name legion \
  --network host \
  --cap-add NET_ADMIN \
  --cap-add NET_RAW \
  -v legion-config:/root/.local/share/legion \
  -v legion-tmp:/tmp/legion \
  legion

# Logs
sudo docker logs -f legion

# Open http://127.0.0.1:5000 in your browser

# Stop
sudo docker stop legion && sudo docker rm legion
```

**Custom port:**
```bash
sudo docker run -d --name legion \
  --network host --cap-add NET_ADMIN --cap-add NET_RAW \
  -v legion-config:/root/.local/share/legion \
  legion --port 8080
# Open http://127.0.0.1:8080
```

**Save projects to a host directory:**
```bash
sudo docker run -d --name legion \
  --network host --cap-add NET_ADMIN --cap-add NET_RAW \
  -v legion-config:/root/.local/share/legion \
  -v /home/kali/legion-projects:/projects \
  legion
# Files saved via File → Save As appear in /home/kali/legion-projects/
```

**Open a shell inside the container:**
```bash
sudo docker exec -it legion bash
```

### Docker — verify from a clean image

This builds from scratch on a fresh Kali image and runs the install verification tests:

```bash
sudo docker build --no-cache -f Dockerfile.test -t legion-test .
sudo docker run --rm legion-test
# Expected: 22 passed, 71 skipped
# (tool binary tests skip inside Docker — they run on the host)
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

Press **F2** → **⊞ Easy Edit** to configure everything through a structured GUI — no need to know the conf syntax. The Scheduler tab shown below controls which tools fire automatically when a service is discovered.

![Easy Edit — Scheduler tab showing 50 auto-run tool entries with service filters](gifs/shots/easy_mode_scheduler.png)

To edit the raw conf directly:
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
