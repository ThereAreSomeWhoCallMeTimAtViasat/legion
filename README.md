![LegionnAIre](images/LegionnaireBannerGood.png)

![LegionnAIre main interface](gifs/shots/hero_full.png)

---

## What is LegionnAIre?

LegionnAIre is an open source, semi-automated network penetration testing framework for discovery, reconnaissance, and exploitation. It is a fork of [Legion](https://github.com/GoVanguard/legion), which was itself a fork of [Sparta](https://github.com/SECFORCE/sparta) — a tool that has been in active pentest use since 2015.

The core workflow is the same as it has always been:

1. **Add targets** — IPs, CIDRs, hostnames, or ranges. LegionnAIre adds them to scope.
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

While I was in there I added the things I'd always wanted: Interactive terminals, AI host analysis (Anthropic Claude, Google Gemini, OpenAI, or local models), tool keyword match highlighting with navigation arrows, better note taking, parallel nmap stages, a config GUI so you don't have to hand-edit `legion.conf`, and several other UI features. There is a full selenium test suite for developers.  The name **LegionnAIre** reflects the AI addition and its Legion roots.

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
- Layout identical to the original Legion/LegionnAIre desktop app: host list left, tabbed panels right, process list bottom
- **All splitters draggable** with saved position; **font size controls** for upper and lower panels independently
- **Sticky process table header**, scrollable tab bar, context menus that stay in viewport
- Opens Firefox automatically on start with a dedicated isolated profile

![Process output with ANSI colour](gifs/shots/output_annotated.png)

### AI host analysis (multi-provider)
- **Phase 1 — Synthesizer**: reads all tool output, NSE scripts, CVEs, and analyst notes for a host; extracts a structured findings table (severity-coded Critical/High/Medium/Low/Info)
- **Phase 2 — Attack Planner**: on-demand; takes Phase 1 findings as input and produces a specific, actionable attack plan with exact commands
- **Persistent history DB** at `~/.local/share/legion/ai_history.db` — analyses survive project switches; Jaccard similarity matching shows historical hosts that look like the current target (≥95% match on port/service/version fingerprint)
- **Three provider backends** — configure in `legion.conf` `[AISettings]`:
  - **Anthropic** — direct API key auth (`api.anthropic.com`)
  - **Google Vertex AI** — Claude on GCP via Application Default Credentials
  - **OpenAI-compatible** — works with OpenAI, Google Gemini, Azure OpenAI, ollama, vLLM, LM Studio, or any provider that speaks the OpenAI chat completions API

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

> **Important:** The Flask web UI lives on **two branches**:
> - **`flask-clean-prod`** — stable release branch. Use this for normal installs.
> - **`flask-clean`** — development branch. Use this if you want the latest changes or plan to contribute.
>
> The default `master` branch is the original upstream Qt5 desktop app.
> The `--branch` flag below is **required** — without it you will clone
> the wrong codebase and `python3 legion.py --web` will not exist.

```bash
# Production install (recommended)
sudo git clone --branch flask-clean-prod https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion

# Confirm you are on the right branch before continuing
sudo git branch        # should show: * flask-clean-prod

sudo bash install.sh
```

To install the **development branch** instead:
```bash
sudo git clone --branch flask-clean https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion
sudo bash install.sh
```

**Options:**

| Flag | Effect |
|---|---|
| `--no-ai` | Skip the AI provider setup prompt at the end |

---

## Installation — Manual (step by step)

Use this if you need to understand what each step does, skip certain parts, or troubleshoot a failed automated install.

### Step 1 — Clone the repository onto the correct branch

The repository has multiple branches:
- **`flask-clean-prod`** — stable release branch (recommended for most users)
- **`flask-clean`** — development branch (latest changes, may be less stable)
- `master` — original upstream Qt5 desktop app (does not have `--web` mode)

```bash
# Production (recommended)
sudo git clone --branch flask-clean-prod \
    https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion

# Or development branch:
# sudo git clone --branch flask-clean \
#     https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git

# Verify you are on the right branch before doing anything else
sudo git branch
# Output must show:   * flask-clean-prod   (or * flask-clean for dev)
# If it shows master or anything else, run:  sudo git checkout flask-clean-prod

sudo git log --oneline -3
# Should show recent commits starting with "v10.xxx" version tags
```

### Step 2 — Install Python packages

`requirements.txt` covers **both** Flask web mode and Qt6 GUI mode.

```bash
sudo pip3 install --break-system-packages -r requirements.txt
```

Expected output: a list of packages being installed, ending with `Successfully installed ...`

**Verify:**
```bash
python3 -c "import flask, PyQt6.QtCore, sqlalchemy, anthropic, openai; print('OK')"
# Expected: OK
```

If this fails, check:
- Python version: `python3 --version` must be 3.10+
- pip is available: `python3 -m pip --version`
- On Ubuntu you may need: `sudo apt-get install python3-pip python3-dev`

### Step 3 — Install system security tools

`install.sh` handles everything in one pass. If you are doing a manual install,
run it with `sudo` — it installs apt packages, Go binaries, GitHub tools, and
Python `/opt` tools, all requiring root:

```bash
sudo bash install.sh --no-ai
```

What it installs beyond what Kali pre-includes:

| Tool | Method | Purpose |
|---|---|---|
| `golang-go` | apt | Required for all Go-based tools |
| `pd-httpx` | Go | HTTP technology detection |
| `katana` | Go | Web crawler |
| `gau` | Go | Passive URL collection |
| `waybackurls` | Go | Wayback Machine URL fetch |
| `nomore403` | Go | 403 bypass checker |
| `urlfinder` | Go | URL extraction |
| `kerbrute` | GitHub binary | Kerberos user enum |
| `rdp-sec-check` | apt / GitHub Perl | RDP security audit |
| `jexboss` | `sudo git clone` → `/opt/jexboss` | JBoss vulnerability scanner |
| `LeakSearch` | `sudo git clone` → `/opt/LeakSearch` | Credential leak search |
| `nuclei templates` | `nuclei -update-templates` | Required before nuclei can scan |

All individual install commands inside the script run with `sudo` — apt-get,
sudo git clone, sudo pip install, go install, curl, cp, chmod.  Expected runtime:
5–15 minutes depending on network speed.

**Verify individual tools after install:**
```bash
for t in pd-httpx katana gau waybackurls nomore403 urlfinder kerbrute nuclei ssh-audit; do
    command -v $t && echo "✓ $t" || echo "✗ $t — missing"
done
```

### Step 4 — geckodriver (required for Selenium tests and screenshooter)

**On Kali:** geckodriver is already at `/usr/bin/geckodriver` — nothing to do.

**On Ubuntu:**
```bash
# Find the latest release at https://github.com/mozilla/geckodriver/releases
GECKODRIVER_VERSION="v0.35.0"
sudo curl -fsSL \
    "https://github.com/mozilla/geckodriver/releases/download/${GECKODRIVER_VERSION}/geckodriver-${GECKODRIVER_VERSION}-linux64.tar.gz" \
    | sudo tar xz -C /usr/local/bin
sudo chmod +x /usr/local/bin/geckodriver
geckodriver --version   # verify
```

### Step 5 — (Optional) AI tab — choose a provider

The AI tab supports multiple backends. Pick **one** of the options below and
configure it in `legion.conf` under `[AISettings]`. You can edit this section
via Config Manager (F2 → Easy Edit or Advanced mode) or directly:

```bash
sudoedit /root/.local/share/legion/legion.conf
```

Scroll to the `[AISettings]` section at the bottom of the file.

#### Option A — Anthropic direct API (simplest)

Get an API key from [console.anthropic.com](https://console.anthropic.com/).

```ini
[AISettings]
ai_provider=anthropic
ai_api_key=sk-ant-api03-YOUR-KEY-HERE
ai_model=claude-sonnet-4-6
ai_api_url=
ai_vertex_project_id=
ai_vertex_region=global
```

#### Option B — Google Gemini

Get an API key from [Google AI Studio](https://aistudio.google.com/apikey).
This uses Google's OpenAI-compatible endpoint — no GCP project required.

```ini
[AISettings]
ai_provider=openai
ai_api_key=YOUR-GEMINI-API-KEY
ai_model=gemini-2.5-flash
ai_api_url=https://generativelanguage.googleapis.com/v1beta/openai/
ai_vertex_project_id=
ai_vertex_region=global
```

Available Gemini models: `gemini-2.5-flash` (fast/cheap), `gemini-2.5-pro` (most capable), `gemini-2.0-flash`.

#### Option C — OpenAI

```ini
[AISettings]
ai_provider=openai
ai_api_key=sk-YOUR-OPENAI-KEY
ai_model=gpt-4o
ai_api_url=
ai_vertex_project_id=
ai_vertex_region=global
```

#### Option D — Local models (ollama, vLLM, LM Studio)

Any server that speaks the OpenAI chat completions API works. No API key needed for local servers.

```ini
[AISettings]
ai_provider=openai
ai_api_key=not-needed
ai_model=llama3
ai_api_url=http://localhost:11434/v1/
ai_vertex_project_id=
ai_vertex_region=global
```

For **ollama**: `ai_api_url=http://localhost:11434/v1/`
For **vLLM**: `ai_api_url=http://localhost:8000/v1/`
For **LM Studio**: `ai_api_url=http://localhost:1234/v1/`

#### Option E — Google Vertex AI (GCP)

For users who access Claude through a Google Cloud project. Uses Application
Default Credentials — no API key stored.

**Prerequisites:** a GCP project with the Vertex AI API enabled.

```bash
gcloud auth application-default login
```

```ini
[AISettings]
ai_provider=vertex
ai_api_key=
ai_model=claude-sonnet-4-6
ai_api_url=
ai_vertex_project_id=your-gcp-project-id
ai_vertex_region=global
```

#### Legacy Vertex AI users

If you previously configured Vertex AI via `~/.claude/settings.json` (the old
method), it still works automatically — LegionnAIre falls back to that file when
`ai_provider` is empty or `none`. No migration required, but moving to
`legion.conf` is recommended.

#### Settings reference

| Setting | Required for | Description |
|---|---|---|
| `ai_provider` | all | `anthropic`, `openai`, or `vertex` |
| `ai_api_key` | anthropic, openai | Your API key (not needed for vertex or local models) |
| `ai_model` | all | Model name (e.g. `claude-sonnet-4-6`, `gpt-4o`, `gemini-2.5-flash`) |
| `ai_api_url` | openai (non-default) | Base URL for the API — leave blank for OpenAI's default; set for Gemini, ollama, etc. |
| `ai_vertex_project_id` | vertex | GCP project ID |
| `ai_vertex_region` | vertex | GCP region (default: `global`) |

### Step 6 — Verify the complete install

Runs 93 tests that check every Python import, verify LegionnAIre starts in web mode, confirm Qt6 works, and check that every tool binary is in PATH:

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

If some tool binary tests fail, run `sudo bash install.sh --no-ai` — step 8 of
the installer automatically detects failed tests, installs the missing tools,
and retries up to three times.

---

## Installation — Docker

Docker gives you LegionnAIre plus all tools in a self-contained image. Scanning still works — the container gets the same raw socket capabilities as the host via `--cap-add`.

> **WSL users:** If you are running Kali in WSL2, skip Docker and install
> directly with `sudo bash install.sh` — it is simpler and avoids the
> networking limitations described in [Docker on WSL](#docker-on-wsl) below.
> Docker is most useful on non-Kali systems (Ubuntu desktop, macOS, CI)
> where you don't want to install 50 security tools on the host.

### Option A — Docker Compose (easiest)

```bash
# Use flask-clean-prod for stable, or flask-clean for development
sudo git clone --branch flask-clean-prod \
    https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion

# Build the image (takes 5–15 minutes; downloads all tools)
sudo docker compose build

# Start LegionnAIre in the background
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

### Docker on WSL

There are two ways to run Docker on WSL2, and they behave differently for
LegionnAIre's network scanning:

#### Docker Engine inside the WSL distro (works)

Install Docker Engine natively inside your Kali WSL2 distro. `--network host`
works correctly — the container shares the WSL2 VM's network namespace, so
nmap and masscan can scan your LAN.

**Prerequisites** — WSL2 Kali does not ship with systemd or the right iptables
backend, so two things must be fixed first:

```bash
# 1. Enable systemd (required for dockerd to start as a service)
#    Add to /etc/wsl.conf:
echo -e '[boot]\nsystemd=true' | sudo tee -a /etc/wsl.conf

# 2. Restart WSL from PowerShell:
#    wsl --shutdown
#    (then relaunch Kali)

# 3. Switch to iptables-legacy (Docker does not work with nftables)
sudo update-alternatives --set iptables /usr/sbin/iptables-legacy

# 4. Install Docker
sudo apt update && sudo apt install -y docker.io docker-compose-v2

# 5. Clone and run LegionnAIre
sudo git clone --branch flask-clean-prod \
    https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion
sudo docker compose up -d

# Open http://127.0.0.1:5000 in your Windows browser
```

#### Docker Desktop for Windows with WSL integration (limited)

Docker Desktop uses WSL2 as its backend, but `--network host` does **not**
give true host networking on Windows — this is a known Docker Desktop
limitation. The container gets its own network namespace. Port 5000 will be
accessible (the web UI works), but **scanning LAN targets from inside the
container will fail** because the container cannot send raw packets to your
physical network.

If you already have Docker Desktop, LegionnAIre's web UI will work for importing
existing nmap XML files and reviewing saved projects — but live scanning
requires either the native install or Docker Engine inside WSL (above).

#### Recommendation for WSL users

For a clean Kali WSL2 install, **skip Docker entirely** and install directly:

```bash
sudo git clone --branch flask-clean-prod \
    https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion.git
cd legion
sudo bash install.sh
sudo python3 legion.py --web --no-browser
# Open http://127.0.0.1:5000 in your Windows browser
```

Use `--no-browser` because WSL2 without WSLg has no GUI. If you have WSLg
(Windows 11 22H2+), Firefox will open automatically without the flag.

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
| `[AISettings]` | AI provider, API key, model, endpoint URL |

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
