"""
LEGION (https://github.com/ThereAreSomeWhoCallMeTimAtViasat/legion)
Author: Tim McLean (Viasat, Inc.)
Copyright (c) 2025-2026 Viasat, Inc.
Copyright (c) 2025 Shane William Scott (original Legion)

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful, but
    WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
    General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.

THIS SOFTWARE IS PROVIDED BY VIASAT, INC. "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES ARE DISCLAIMED. IN NO EVENT SHALL VIASAT, INC. BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE.
"""

"""
AI Analyzer — assembles host data, runs two-phase AI pipeline,
saves results to both the persistent history DB and the project DB.

Supports multiple AI providers:
  - vertex:    Anthropic Claude via Google Cloud Vertex AI (GCP ADC auth)
  - anthropic: Anthropic Claude direct API (API key auth)
  - openai:    OpenAI-compatible API (OpenAI, Azure, ollama, vLLM, LM Studio)

Phase 1 (Synthesizer): raw DB data → structured JSON findings array
Phase 2 (Attack Planner): JSON findings → Markdown attack plan

Called from routes: POST /api/ai/analyze-host/<host_id>
"""

import json
import logging
import os
import re
import shlex
import shutil
import threading
import time
import uuid
from datetime import datetime

from app.ai import history_db
from app.auxiliary import Filters

log = logging.getLogger('legion')

# Pricing for cost estimation (per million tokens, USD) — Anthropic defaults
_INPUT_COST_PER_MTOK  = 3.0
_OUTPUT_COST_PER_MTOK = 15.0
_CHARS_PER_TOKEN      = 4      # rough approximation

_CONF_PATH = os.path.expanduser('~/.local/share/legion/legion.conf')


def _read_ai_config():
    """Read AI provider settings from legion.conf [AISettings] section.

    Falls back to ~/.claude/settings.json for existing Vertex AI users who
    haven't migrated yet.

    Returns dict with keys: provider, api_key, model, api_url,
                            vertex_project_id, vertex_region.
    """
    import configparser
    cfg = configparser.RawConfigParser()
    cfg.read(_CONF_PATH)

    provider   = ''
    api_key    = ''
    model      = ''
    api_url    = ''
    vertex_pid = ''
    vertex_reg = 'global'

    if cfg.has_section('AISettings'):
        provider   = cfg.get('AISettings', 'ai_provider', fallback='').strip()
        api_key    = cfg.get('AISettings', 'ai_api_key', fallback='').strip()
        model      = cfg.get('AISettings', 'ai_model', fallback='').strip()
        api_url    = cfg.get('AISettings', 'ai_api_url', fallback='').strip()
        vertex_pid = cfg.get('AISettings', 'ai_vertex_project_id', fallback='').strip()
        vertex_reg = cfg.get('AISettings', 'ai_vertex_region', fallback='global').strip()

    # Fallback: if provider is empty/none, check ~/.claude/settings.json
    # for the legacy Vertex AI config
    if not provider or provider == 'none':
        legacy = _read_legacy_vertex_config()
        if legacy:
            provider   = 'vertex'
            vertex_pid = legacy['project_id']
            vertex_reg = legacy['region']
            model      = legacy['model']

    # Auto-detect Vertex project ID when provider is vertex but no
    # project ID was set — check legacy config, then gcloud CLI
    if provider == 'vertex' and not vertex_pid:
        legacy = _read_legacy_vertex_config()
        if legacy:
            vertex_pid = legacy['project_id']
            vertex_reg = legacy.get('region', vertex_reg)
            if not model:
                model = legacy['model']
        if not vertex_pid:
            vertex_pid = _read_gcloud_project_id()

    if not model:
        if provider == 'openai':
            model = 'gpt-4o'
        else:
            model = 'claude-sonnet-4-6'

    return {
        'provider':          provider,
        'api_key':           api_key,
        'model':             model,
        'api_url':           api_url,
        'vertex_project_id': vertex_pid,
        'vertex_region':     vertex_reg,
    }


def _read_legacy_vertex_config():
    """Read legacy Vertex AI config from ~/.claude/settings.json.
    Returns dict or None if not configured."""
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        settings_path = f'/home/{sudo_user}/.claude/settings.json'
    else:
        settings_path = os.path.expanduser('~/.claude/settings.json')
    try:
        with open(settings_path) as f:
            s = json.load(f)
        env  = s.get('env', {})
        proj = env.get('ANTHROPIC_VERTEX_PROJECT_ID', '')
        if not proj:
            return None
        return {
            'project_id': proj,
            'region': env.get('CLOUD_ML_REGION', 'global'),
            'model': s.get('model', 'claude-sonnet-4-6').replace('[1m]', ''),
        }
    except Exception:
        return None


def _read_gcloud_project_id():
    """Try to read the default GCP project from gcloud CLI config."""
    import subprocess
    try:
        result = subprocess.run(
            ['gcloud', 'config', 'get-value', 'project'],
            capture_output=True, text=True, timeout=5,
        )
        val = result.stdout.strip()
        if val and val != '(unset)':
            return val
    except Exception:
        pass
    return ''


def _find_adc_path():
    """Return the path to GCP ADC credentials file, or '' if not found."""
    explicit = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
    if explicit and os.path.exists(explicit):
        return explicit
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        p = f'/home/{sudo_user}/.config/gcloud/application_default_credentials.json'
        if os.path.exists(p):
            return p
    p = os.path.expanduser('~/.config/gcloud/application_default_credentials.json')
    if os.path.exists(p):
        return p
    return ''


class _OpenAIAdapter:
    """Wraps the OpenAI chat completions API to match the Anthropic
    messages.create() interface used by the rest of analyzer.py."""

    def __init__(self, api_key, base_url=None):
        from openai import OpenAI
        kwargs = {'api_key': api_key}
        if base_url:
            kwargs['base_url'] = base_url
        self._client = OpenAI(**kwargs)
        self.messages = self

    def create(self, *, model, max_tokens, system, messages):
        oai_messages = [{'role': 'system', 'content': system}]
        for m in messages:
            oai_messages.append({'role': m['role'], 'content': m['content']})

        resp = self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
        )
        return _OpenAIResponse(resp)


class _OpenAIResponse:
    """Adapts OpenAI ChatCompletion response to Anthropic response shape."""

    def __init__(self, resp):
        choice = resp.choices[0]
        self.content = [_TextBlock(choice.message.content or '')]
        u = resp.usage
        self.usage = _Usage(
            getattr(u, 'prompt_tokens', 0) or 0,
            getattr(u, 'completion_tokens', 0) or 0,
        )


class _TextBlock:
    def __init__(self, text):
        self.text = text


class _Usage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def _get_client(config=None):
    """Factory: return an AI client based on the configured provider."""
    if config is None:
        config = _read_ai_config()

    provider = config['provider']

    if provider == 'vertex':
        from anthropic import AnthropicVertex
        # When running as root via sudo, ADC credentials live under the
        # original user's home, not /root.
        if 'GOOGLE_APPLICATION_CREDENTIALS' not in os.environ:
            sudo_user = os.environ.get('SUDO_USER')
            if sudo_user:
                adc_path = f'/home/{sudo_user}/.config/gcloud/application_default_credentials.json'
                if os.path.exists(adc_path):
                    os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = adc_path
                    log.debug(f"[AI] Using ADC from {adc_path}")
        return AnthropicVertex(
            project_id=config['vertex_project_id'],
            region=config['vertex_region'],
        )

    if provider == 'anthropic':
        from anthropic import Anthropic
        return Anthropic(api_key=config['api_key'])

    if provider == 'openai':
        return _OpenAIAdapter(
            api_key=config['api_key'],
            base_url=config['api_url'] or None,
        )

    raise ValueError(
        f"AI provider not configured. Set ai_provider in legion.conf "
        f"[AISettings] to one of: vertex, anthropic, openai"
    )


def estimate_cost(text_length_chars):
    """Rough pre-flight cost estimate. Returns (est_tokens_input, est_cost_usd)."""
    est_tokens_input  = text_length_chars // _CHARS_PER_TOKEN
    est_tokens_output = 1000  # assume ~1k output tokens
    cost = (est_tokens_input  / 1_000_000 * _INPUT_COST_PER_MTOK +
            est_tokens_output / 1_000_000 * _OUTPUT_COST_PER_MTOK)
    return est_tokens_input, round(cost, 4)


def _actual_cost(usage):
    """Compute actual cost from Anthropic usage object."""
    tin  = getattr(usage, 'input_tokens',  0) or 0
    tout = getattr(usage, 'output_tokens', 0) or 0
    return tin, tout, round(
        tin  / 1_000_000 * _INPUT_COST_PER_MTOK +
        tout / 1_000_000 * _OUTPUT_COST_PER_MTOK, 4)


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def _assemble_host_data(logic, host_id):
    """
    Gather all DB data for host_id and return:
      (host_obj, ports, cves, scripts, note_text, processes, fingerprint, os_family)
    """
    rc      = logic.activeProject.repositoryContainer
    filters = Filters()

    # Host object
    session  = rc.hostRepository.dbAdapter.session()
    from db.entities.host import hostObj as HostObj
    host_obj = session.query(HostObj).filter(HostObj.id == host_id).first()
    if not host_obj:
        return None
    host_ip  = host_obj.ip
    os_family = str(host_obj.osMatch or '')

    # Ports + services (plain dicts, no ORM detachment)
    ports = rc.portRepository.getPortsAndServicesByHostIP(host_ip, filters) or []

    # CVEs
    cves = rc.cveRepository.getCVEsByHostIP(host_ip) or []

    # NSE scripts
    scripts = rc.scriptRepository.getScriptsByHostIP(host_ip) or []

    # Notes
    note_obj  = rc.noteRepository.getNoteByHostId(host_id)
    note_text = (note_obj.text if note_obj else '') or ''

    # Processes — all for this host, output stored in DB.
    # showProcesses=True uses LEFT JOIN with process_output so the 'output'
    # field is already populated from the DB; exclude nmap (verbose progress
    # text) and screenshooter (no textual findings).
    all_procs = rc.processRepository.getProcesses(
        filters, showProcesses=True, sort='desc', ncol='id')
    host_procs = [p for p in all_procs
                  if str(p.get('hostIp', '')) == host_ip
                  and p.get('name', '') not in ('screenshooter', 'nmap')]

    # Build fingerprint
    fingerprint = history_db.build_fingerprint(ports, os_family)

    return (host_obj, host_ip, os_family, ports, cves, scripts,
            note_text, host_procs, fingerprint)


def _build_phase1_prompt(host_obj, host_ip, os_family, ports, cves,
                          scripts, note_text, processes):
    """Assemble the full text block sent to Phase 1."""
    parts = []

    # Host header
    parts.append(f"HOST: {host_ip}")
    if host_obj.hostname:
        parts.append(f"Hostname: {host_obj.hostname}")
    if os_family:
        parts.append(f"OS: {os_family}")
    parts.append(f"State: {host_obj.state or 'up'}")
    parts.append("")

    # Open ports + services  (keys match getPortsAndServicesByHostIP return dict)
    parts.append("=== OPEN PORTS AND SERVICES ===")
    for p in ports:
        port     = p.get('portId') or p.get('port_number') or p.get('port', '')
        proto    = p.get('protocol', 'tcp')
        svc      = p.get('name') or p.get('service_name') or p.get('service', '')
        ver      = p.get('version') or p.get('service_version') or p.get('product', '')
        state    = p.get('state', 'open')
        line     = f"  {port}/{proto}  {state}  {svc}"
        if ver:
            line += f"  ({ver})"
        parts.append(line)
    parts.append("")

    # CVEs
    if cves:
        parts.append("=== CVEs (from vulners NSE) ===")
        for c in cves:
            name = getattr(c, 'name', '') if not isinstance(c, dict) else c.get('name', '')
            sev  = getattr(c, 'severity', '') if not isinstance(c, dict) else c.get('severity', '')
            prod = getattr(c, 'product', '') if not isinstance(c, dict) else c.get('product', '')
            parts.append(f"  {name}  CVSS:{sev}  {prod}")
        parts.append("")

    # NSE scripts
    if scripts:
        parts.append("=== NSE SCRIPT OUTPUT ===")
        for s in scripts:
            port   = getattr(s, 'port', '') if not isinstance(s, dict) else s.get('port', '')
            name   = getattr(s, 'name', '') if not isinstance(s, dict) else s.get('name', '')
            output = getattr(s, 'output', '') if not isinstance(s, dict) else s.get('output', '')
            if output and output.strip():
                parts.append(f"  [{port}] {name}: {str(output).strip()[:500]}")
        parts.append("")

    # Analyst notes
    if note_text and note_text.strip():
        parts.append("=== ANALYST NOTES ===")
        parts.append(note_text.strip()[:2000])
        parts.append("")

    # Tool outputs — matched first, then by id desc, truncated
    if processes:
        parts.append("=== TOOL OUTPUTS ===")
        matched   = [p for p in processes if p.get('has_match') or p.get('match_text')]
        unmatched = [p for p in processes if not (p.get('has_match') or p.get('match_text'))]
        for proc in matched + unmatched:
            name   = proc.get('name', 'tool')
            status = proc.get('status', '')
            output = proc.get('output', '') or ''
            if not output or not output.strip():
                continue
            parts.append(f"--- {name} ({status}) ---")
            parts.append(output.strip()[:2000])
            parts.append("")

    return '\n'.join(parts)


_PHASE1_SYSTEM = (
    "You are a data extraction assistant. Extract all significant security findings "
    "from this raw penetration test data. Output structured JSON only: an array of "
    "findings, each with fields: source (tool name), port (if applicable, else null), "
    "severity (critical/high/medium/low/info), finding (one sentence), evidence "
    "(brief quote from output). Deduplicate. Omit informational noise. "
    "Return ONLY valid JSON — no markdown fences, no explanation."
)

_PHASE2_SYSTEM = (
    "You are a senior penetration tester. Given these confirmed findings from a target "
    "host, identify: 1) exploitable vulnerabilities with specific CVEs or techniques, "
    "2) recommended next tools and exact commands to run, 3) likely attack paths ranked "
    "by probability of success, 4) misconfigurations to investigate. "
    "Be specific and actionable. Format your response in clear Markdown.\n\n"
    "PRIORITY RULES:\n"
    "- Findings in the CONFIRMED BY TARGETED ENUMERATION section were produced by "
    "tools that an AI gap analysis specifically selected to confirm suspected "
    "vulnerabilities. These are the highest-confidence findings — rank attack paths "
    "that use them above paths based on generic scan data alone.\n"
    "- Obvious attacks listed in the GAP ANALYSIS section have already been validated "
    "by the enumeration phase. Include them as confirmed attack paths with exact "
    "exploitation commands, not as suggestions to investigate.\n"
    "- For any credentials, hashes, or passwords found, include the exact cracking "
    "command (hashcat -m MODE) and the next post-authentication step."
)


# ---------------------------------------------------------------------------
# Enhanced Phase 1 — gap analysis + tool execution + re-synthesis
# ---------------------------------------------------------------------------

_SAFE_COMMAND_BINARIES = frozenset({
    'curl', 'searchsploit', 'smbclient', 'redis-cli', 'dig', 'host',
    'whois', 'openssl', 'rpcclient', 'ldapsearch', 'gpp-decrypt', 'net', 'nmap',
})

_INJECTION_PATTERNS = (';', '`', '$(', '&&', '||')

_TOOL_PACKAGE_MAP = {
    'enum4linux-ng': 'enum4linux-ng', 'feroxbuster': 'feroxbuster',
    'searchsploit': 'exploitdb', 'redis-cli': 'redis-tools',
    'smbclient': 'smbclient', 'ssh-audit': 'ssh-audit',
    'gobuster': 'gobuster', 'nikto': 'nikto', 'whatweb': 'whatweb',
    'wpscan': 'wpscan', 'nuclei': 'nuclei',
    'rpcclient': 'smbclient', 'ldapsearch': 'ldap-utils',
    'impacket-GetNPUsers': 'python3-impacket',
    'impacket-lookupsid': 'python3-impacket',
    'impacket-GetUserSPNs': 'python3-impacket',
    'gpp-decrypt': 'gpp-decrypt', 'nmap': 'nmap',
    'certipy-ad': 'certipy-ad', 'adidnsdump': 'adidnsdump',
    'ldeep': 'ldeep', 'windapsearch': 'windapsearch',
    'subfinder': 'subfinder', 'hashcat': 'hashcat', 'john': 'john',
}

_GAP_ANALYSIS_SYSTEM = (
    "You are a penetration testing enumeration planner. Given the current findings "
    "and available tools, identify coverage gaps and recommend additional enumeration.\n\n"
    "Rules:\n"
    "- Recommend tools from the AVAILABLE TOOLS list by their exact tool_id\n"
    "- You may provide a command_override to customize the command for this specific target\n"
    "  - command_override MUST use the SAME binary as the tool's default command\n"
    "  - command_override MUST include [IP] and [OUTPUT] placeholders ([PORT] if port-specific)\n"
    "  - command_override MUST NOT contain: backticks, $(), ;, &&, ||\n"
    "  - Use command_override when: a subdirectory was found (scan deeper), a CMS was\n"
    "    identified (use CMS-specific wordlist), a domain name was discovered (pass to\n"
    "    AD tools), or a specific vulnerability indicator needs confirmation\n"
    "- Do NOT recommend tools that appear in the ALREADY RUN list\n"
    "- Do NOT recommend full nmap port scans — only targeted --script invocations\n"
    "- Limit to at most 8 tool recommendations + 4 safe_commands\n"
    "- For safe_commands, ONLY use: curl, searchsploit, smbclient, redis-cli, dig, "
    "host, whois, openssl, rpcclient, ldapsearch, gpp-decrypt, nmap\n"
    "- safe_commands must be read-only enumeration — no exploitation, no reverse shells\n"
    "- Flag obvious_attacks that don't need more data (include next_command with the "
    "exact command the user should run, including hashcat mode numbers for hashes)\n"
    "- When Active Directory indicators are detected (port 88 Kerberos, port 389 LDAP, "
    "port 445 with domain controller services), prioritize AD-specific tools: "
    "ldapsearch-anon, ldapsearch-users, ldapsearch-all-attrs, rpcclient-null-enum, "
    "impacket-lookupsid-null, impacket-getnpusers-nopass, gpp-extract, gpp-sysvol-check, "
    "nmap-smb-vuln, certipy-find, ldeep-enum, windapsearch-users, responder-finger\n"
    "- When recommending AD tools with YOURDOMAIN/ placeholder, use command_override to "
    "substitute the actual domain name if discovered from LDAP/SMB enumeration\n"
    "- When LDAP is detected, always recommend ldapsearch-all-attrs (query '*') — custom "
    "attributes like cascadeLegacyPwd, ms-MCS-AdmPwd, unixUserPassword often contain creds\n"
    "- Return ONLY valid JSON — no markdown fences, no explanation\n\n"
    "Output JSON:\n"
    '{\n'
    '  "recommended_tools": [\n'
    '    {"tool_id": "...", "port": "...", "protocol": "tcp", '
    '"rationale": "...", "command_override": "..."}\n'
    '  ],\n'
    '  "obvious_attacks": [\n'
    '    {"severity": "critical|high|medium", "attack": "...", '
    '"evidence": "...", "next_command": "..."}\n'
    '  ],\n'
    '  "safe_commands": [\n'
    '    {"command": "curl -sk https://[IP]:[PORT]/robots.txt", "rationale": "..."}\n'
    '  ]\n'
    '}'
)

_PHASE1_RESYNTHESIS_EXTRA = (
    "\n\nAdditionally:\n"
    "- Flag any plaintext passwords, password hashes (NTLM, NetNTLMv2, AS-REP, "
    "Kerberoastable, GPP cpassword), base64-encoded credentials, or API keys found "
    "in tool output as CRITICAL findings. Include the exact credential value in the "
    "evidence field.\n"
    "- Identify the hash type and include the hashcat mode number when a hash is found "
    "(e.g., AS-REP = -m 18200, NetNTLMv2 = -m 5600, NTLM = -m 1000)\n"
    "- Flag service accounts, administrator accounts, or accounts with 'Do not require "
    "Kerberos pre-authentication' as HIGH findings"
)

_MAX_TOOLS = 8
_MAX_SAFE_COMMANDS = 4
_TOOL_EXEC_TIMEOUT = 300  # 5 minutes

# In-memory job store
_jobs = {}
_jobs_lock = threading.Lock()
_job_approval_events = {}


def _build_known_binaries(settings):
    """Extract all binary names from portActions and hostActions command templates."""
    binaries = set(_SAFE_COMMAND_BINARIES)
    for action in (settings.portActions or []):
        cmd = str(action[2]) if len(action) > 2 else ''
        if cmd:
            tok = cmd.split()[0] if cmd.split() else ''
            binaries.add(os.path.basename(tok))
    for action in (settings.hostActions or []):
        cmd = str(action[2]) if len(action) > 2 else ''
        if cmd:
            tok = cmd.split()[0] if cmd.split() else ''
            binaries.add(os.path.basename(tok))
    binaries.discard('')
    return frozenset(binaries)


def _validate_command_override(override, tool_id, settings):
    """Validate a command override from the LLM.
    Returns (is_valid, reason)."""
    if not override or not override.strip():
        return False, 'empty override'

    for pat in _INJECTION_PATTERNS:
        if pat in override:
            return False, f'injection pattern {pat!r} detected'

    tokens = override.split()
    if not tokens:
        return False, 'no tokens in override'
    override_binary = os.path.basename(tokens[0])

    conf_binary = None
    for action in (settings.portActions or []):
        if str(action[1]).strip() == tool_id:
            conf_cmd = str(action[2]) if len(action) > 2 else ''
            if conf_cmd:
                conf_binary = os.path.basename(conf_cmd.split()[0])
            break
    if not conf_binary:
        for action in (settings.hostActions or []):
            if str(action[1]).strip() == tool_id:
                conf_cmd = str(action[2]) if len(action) > 2 else ''
                if conf_cmd:
                    conf_binary = os.path.basename(conf_cmd.split()[0])
                break

    if conf_binary and override_binary != conf_binary:
        return False, f'binary mismatch: override={override_binary}, conf={conf_binary}'

    known = _build_known_binaries(settings)
    if override_binary not in known:
        return False, f'unknown binary: {override_binary}'

    if '[IP]' not in override:
        return False, 'missing [IP] placeholder'

    return True, 'ok'


def _validate_safe_command(command):
    """Validate a safe_command from the LLM. Returns (is_valid, reason)."""
    if not command or not command.strip():
        return False, 'empty command'

    for pat in _INJECTION_PATTERNS:
        if pat in command:
            return False, f'injection pattern {pat!r} detected'

    tokens = command.split()
    if not tokens:
        return False, 'no tokens'
    binary = os.path.basename(tokens[0])
    if binary not in _SAFE_COMMAND_BINARIES:
        return False, f'binary {binary!r} not in safe allowlist'

    return True, 'ok'


def _check_tool_installed(command):
    """Check if the binary in a command is installed.
    Returns (binary_name, is_installed, package_name)."""
    tokens = command.split()
    if not tokens:
        return ('', False, '')
    binary = os.path.basename(tokens[0])
    # python3 scripts are always available
    if binary == 'python3':
        return (binary, True, '')
    installed = shutil.which(binary) is not None
    package = _TOOL_PACKAGE_MAP.get(binary, binary)
    return (binary, installed, package)


def _build_tool_catalog(settings):
    """Build a text catalog of available tools for the gap analysis prompt."""
    lines = []
    lines.append("AVAILABLE TOOLS (PortActions):")
    for action in (settings.portActions or []):
        label = str(action[0])
        tool_id = str(action[1]).strip()
        cmd = str(action[2]) if len(action) > 2 else ''
        svc_filter = str(action[3]) if len(action) > 3 else ''
        binary = os.path.basename(cmd.split()[0]) if cmd.split() else ''
        installed = 'yes' if shutil.which(binary) else 'no' if binary else '?'
        lines.append(f"  tool_id={tool_id} | services={svc_filter} | "
                     f"cmd={cmd[:120]} | installed={installed}")

    lines.append("")
    lines.append("AVAILABLE TOOLS (HostActions):")
    for action in (settings.hostActions or []):
        label = str(action[0])
        tool_id = str(action[1]).strip()
        cmd = str(action[2]) if len(action) > 2 else ''
        binary = os.path.basename(cmd.split()[0]) if cmd.split() else ''
        installed = 'yes' if shutil.which(binary) else 'no' if binary else '?'
        lines.append(f"  tool_id={tool_id} | cmd={cmd[:120]} | installed={installed}")

    return '\n'.join(lines)


def _build_already_ran(processes):
    """Build a text list of tools already executed for this host."""
    lines = ["ALREADY RUN (do not re-recommend):"]
    seen = set()
    for proc in processes:
        name = proc.get('name', '')
        status = proc.get('status', '')
        port = proc.get('port', '')
        key = f"{name}:{port}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"  {name} (port {port}, status={status})")
    return '\n'.join(lines)


def _build_gap_analysis_prompt(phase1_findings, host_ip, ports, processes, tool_catalog):
    """Assemble the full prompt for the gap analysis LLM call."""
    parts = [
        f"HOST: {host_ip}",
        "",
        "OPEN PORTS AND SERVICES:",
    ]
    for p in ports:
        port = p.get('portId') or p.get('port_number') or p.get('port', '')
        proto = p.get('protocol', 'tcp')
        svc = p.get('name') or p.get('service_name') or ''
        ver = p.get('version') or p.get('service_version') or ''
        parts.append(f"  {port}/{proto} {svc} {ver}")

    parts.append("")
    parts.append("PHASE 1 FINDINGS:")
    if isinstance(phase1_findings, str):
        parts.append(phase1_findings[:4000])
    else:
        parts.append(json.dumps(phase1_findings, indent=2)[:4000])

    parts.append("")
    parts.append(_build_already_ran(processes))
    parts.append("")
    parts.append(tool_catalog)

    return '\n'.join(parts)


def _map_recommendation_to_command(rec, host_ip, port, protocol, settings, output_folder):
    """Map a recommendation dict to a runnable (command, name, outputfile).
    Uses command_override if valid, otherwise falls back to conf template.
    Returns (command, name, outputfile) or None."""
    from app.timing import getTimestamp
    tool_id = rec.get('tool_id', '')
    override = rec.get('command_override', '')

    if override:
        valid, reason = _validate_command_override(override, tool_id, settings)
        if valid:
            outputfile = os.path.join(output_folder,
                                      f"{getTimestamp()}-ai-{tool_id}-{host_ip}-{port}")
            command = (override
                       .replace('[IP]', host_ip)
                       .replace('[PORT]', str(port))
                       .replace('[OUTPUT]', outputfile))
            return command, tool_id, outputfile
        else:
            log.warning(f"[AI] Override rejected for {tool_id}: {reason}")

    for action in (settings.portActions or []):
        if str(action[1]).strip() == tool_id:
            cmd_template = str(action[2]) if len(action) > 2 else ''
            if cmd_template:
                outputfile = os.path.join(output_folder,
                                          f"{getTimestamp()}-ai-{tool_id}-{host_ip}-{port}")
                command = (cmd_template
                           .replace('[IP]', host_ip)
                           .replace('[PORT]', str(port))
                           .replace('[OUTPUT]', outputfile))
                return command, tool_id, outputfile
            break

    for action in (settings.hostActions or []):
        if str(action[1]).strip() == tool_id:
            cmd_template = str(action[2]) if len(action) > 2 else ''
            if cmd_template:
                outputfile = os.path.join(output_folder,
                                          f"{getTimestamp()}-ai-{tool_id}-{host_ip}-{port}")
                command = (cmd_template
                           .replace('[IP]', host_ip)
                           .replace('[PORT]', str(port))
                           .replace('[OUTPUT]', outputfile))
                return command, tool_id, outputfile
            break

    return None


def _parse_llm_json(text):
    """Parse JSON from LLM response, tolerant of markdown fences."""
    cleaned = text.strip()
    if '```' in cleaned:
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned)
        if m:
            cleaned = m.group(1).strip()
    return json.loads(cleaned)


def _job_progress(job, msg):
    """Append a progress message to the job log."""
    job['progress'].append({'ts': time.time(), 'msg': msg})
    log.info(f"[AI-Job {job['job_id']}] {msg}")


def _cleanup_old_jobs():
    """Purge jobs older than 30 minutes."""
    cutoff = time.monotonic() - 1800
    with _jobs_lock:
        stale = [jid for jid, j in _jobs.items() if j['started_at'] < cutoff]
        for jid in stale:
            del _jobs[jid]
            _job_approval_events.pop(jid, None)


def start_phase1_job(logic, host_id, wc):
    """Start an enhanced Phase 1 job in a background thread. Returns job_id."""
    _cleanup_old_jobs()
    job_id = str(uuid.uuid4())[:8]
    job = {
        'job_id': job_id,
        'host_id': host_id,
        'status': 'running',
        'step': 'synthesis',
        'progress': [],
        'proposed_commands': [],
        'approved_commands': [],
        'cost_breakdown': {},
        'result': None,
        'error': None,
        'started_at': time.monotonic(),
    }
    with _jobs_lock:
        _jobs[job_id] = job
    _job_approval_events[job_id] = threading.Event()

    t = threading.Thread(
        target=run_phase1_enhanced,
        args=(logic, host_id, wc, job_id),
        daemon=True,
        name=f'ai-phase1-{job_id}',
    )
    t.start()
    return job_id


def get_job_status(job_id, since_index=0):
    """Return current job state for polling."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return None
    return {
        'job_id': job['job_id'],
        'status': job['status'],
        'step': job['step'],
        'progress': job['progress'][since_index:],
        'progress_total': len(job['progress']),
        'proposed_commands': job['proposed_commands'],
        'approved_commands': job['approved_commands'],
        'cost_breakdown': job['cost_breakdown'],
        'result': job['result'],
        'error': job['error'],
    }


def submit_approval(job_id, approved_indices, install_tools=None):
    """Submit batch approval from the UI. Unblocks the waiting background thread."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return False
    job['approved_commands'] = approved_indices or []
    job['install_tools'] = install_tools or []
    evt = _job_approval_events.get(job_id)
    if evt:
        evt.set()
    return True


def _enrich_processes(processes):
    """Add .live_output fallback for processes without DB output."""
    enriched = []
    for proc in processes:
        output = proc.get('output', '') or ''
        if not output.strip():
            outputfile = proc.get('outputfile', '')
            if outputfile:
                for suffix in ('.live_output', ''):
                    try_path = outputfile + suffix if suffix else outputfile
                    try:
                        with open(try_path, 'r', errors='replace') as _f:
                            output = _f.read()
                        if output.strip():
                            break
                    except Exception:
                        pass
        enriched.append({**proc, 'output': output})
    return enriched


def run_phase1_enhanced(logic, host_id, wc, job_id):
    """Enhanced Phase 1 pipeline: synthesis → gap analysis → approval → execution → re-synthesis."""
    with _jobs_lock:
        job = _jobs[job_id]

    try:
        # ── Step 1: Initial synthesis ────────────────────────────────
        job['step'] = 'synthesis'
        _job_progress(job, 'Phase 1 synthesis starting...')

        result = _assemble_host_data(logic, host_id)
        if result is None:
            raise ValueError(f"Host {host_id} not found in project DB")

        (host_obj, host_ip, os_family, ports, cves, scripts,
         note_text, processes, fingerprint) = result

        enriched_procs = _enrich_processes(processes)

        prompt_text = _build_phase1_prompt(
            host_obj, host_ip, os_family, ports, cves, scripts,
            note_text, enriched_procs)

        config = _read_ai_config()
        model = config['model']
        client = _get_client(config)

        _job_progress(job, f'Calling AI ({model}) for initial synthesis...')
        p1_resp = client.messages.create(
            model=model, max_tokens=8192,
            system=_PHASE1_SYSTEM,
            messages=[{'role': 'user', 'content': prompt_text}],
        )
        p1_text = p1_resp.content[0].text.strip()
        tin1, tout1, cost1 = _actual_cost(p1_resp.usage)
        job['cost_breakdown']['synthesis'] = {
            'tokens_in': tin1, 'tokens_out': tout1, 'cost': cost1,
        }

        try:
            phase1_findings = _parse_llm_json(p1_text)
        except json.JSONDecodeError:
            phase1_findings = [{'source': 'raw', 'port': None, 'severity': 'info',
                                'finding': p1_text[:500], 'evidence': ''}]

        _job_progress(job, f'Synthesis complete: {len(phase1_findings)} findings')

        # ── Step 2: Gap analysis ─────────────────────────────────────
        job['step'] = 'gap_analysis'
        _job_progress(job, 'Analyzing coverage gaps...')

        tool_catalog = _build_tool_catalog(wc.settings)
        gap_prompt = _build_gap_analysis_prompt(
            phase1_findings, host_ip, ports, enriched_procs, tool_catalog)

        _job_progress(job, f'Calling AI ({model}) for gap analysis...')
        gap_resp = client.messages.create(
            model=model, max_tokens=4096,
            system=_GAP_ANALYSIS_SYSTEM,
            messages=[{'role': 'user', 'content': gap_prompt}],
        )
        gap_text = gap_resp.content[0].text.strip()
        tin2, tout2, cost2 = _actual_cost(gap_resp.usage)
        job['cost_breakdown']['gap_analysis'] = {
            'tokens_in': tin2, 'tokens_out': tout2, 'cost': cost2,
        }

        try:
            gap_result = _parse_llm_json(gap_text)
        except json.JSONDecodeError:
            log.warning(f"[AI] Gap analysis returned non-JSON: {gap_text[:200]}")
            gap_result = {'recommended_tools': [], 'obvious_attacks': [], 'safe_commands': []}

        recommended = gap_result.get('recommended_tools', [])[:_MAX_TOOLS]
        safe_commands = gap_result.get('safe_commands', [])[:_MAX_SAFE_COMMANDS]
        obvious_attacks = gap_result.get('obvious_attacks', [])

        _job_progress(job, f'Gap analysis: {len(recommended)} tools, '
                      f'{len(safe_commands)} safe commands, '
                      f'{len(obvious_attacks)} obvious attacks')

        # ── Save partial record (Steps 1+2) so results survive if user leaves ──
        initial_phase1_json = json.dumps(phase1_findings, indent=2)
        gap_json = json.dumps(gap_result, indent=2)
        partial_tin = tin1 + tin2
        partial_tout = tout1 + tout2
        partial_cost = round(
            partial_tin / 1_000_000 * _INPUT_COST_PER_MTOK +
            partial_tout / 1_000_000 * _OUTPUT_COST_PER_MTOK, 4)

        project_name = getattr(
            logic.activeProject, 'name',
            getattr(logic.activeProject, 'projectName', '')) or ''
        ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

        try:
            history_id = history_db.save_session(
                host_ip=host_ip,
                project_name=str(project_name),
                fingerprint=fingerprint,
                phase1_json=initial_phase1_json,
                phase2_markdown='',
                tokens_input=partial_tin,
                tokens_output=partial_tout,
                cost_usd=partial_cost,
                gap_analysis_json=gap_json,
                enum_actions_json='{"proposed":[],"approved_indices":[],"obvious_attacks":[]}',
            )
        except Exception as e:
            log.error(f"[AI] Partial history-DB save failed: {e}")
            history_id = None

        project_analysis_id = None
        rc = logic.activeProject.repositoryContainer
        try:
            session_db = rc.hostRepository.dbAdapter.session()
            from db.entities.ai_analysis import AiAnalysis
            entry = AiAnalysis(
                host_id=int(host_id), timestamp=ts,
                phase1_json=initial_phase1_json, phase2_markdown=None,
                tokens_input=partial_tin, tokens_output=partial_tout,
                cost_usd=partial_cost, history_session_id=history_id,
                gap_analysis_json=gap_json,
                enum_actions_json='{"proposed":[],"approved_indices":[],"obvious_attacks":[]}',
            )
            session_db.add(entry)
            session_db.commit()
            project_analysis_id = entry.id
            _job_progress(job, 'Partial results saved to database')
        except Exception as e:
            try:
                session_db.rollback()
            except Exception:
                pass
            log.error(f"[AI] Partial project-DB save failed: {e}")
        finally:
            try:
                session_db.close()
            except Exception:
                pass

        # Build proposed_commands for batch approval
        running_folder = logic.activeProject.properties.runningFolder
        proposed = []
        idx = 0

        for rec in recommended:
            tool_id = rec.get('tool_id', '')
            port = rec.get('port', '')
            protocol = rec.get('protocol', 'tcp')
            override = rec.get('command_override', '')

            mapped = _map_recommendation_to_command(
                rec, host_ip, port, protocol, wc.settings, running_folder)

            skipped_reason = None
            if not mapped:
                skipped_reason = 'tool_not_found'
            else:
                command, name, outputfile = mapped
                dup = wc.checkDuplicate(tool_id, host_ip, str(port), protocol)
                if dup == 'skip':
                    skipped_reason = 'duplicate'

            if skipped_reason:
                proposed.append({
                    'index': idx, 'tool_id': tool_id,
                    'command': override or f'(conf template for {tool_id})',
                    'rationale': rec.get('rationale', ''),
                    'source': 'recommended_tool',
                    'is_override': bool(override),
                    'installed': True, 'package': '',
                    'port': port,
                    'skipped_reason': skipped_reason,
                })
            else:
                binary, installed, package = _check_tool_installed(command)
                proposed.append({
                    'index': idx, 'tool_id': tool_id,
                    'command': command,
                    'rationale': rec.get('rationale', ''),
                    'source': 'recommended_tool',
                    'is_override': bool(override) and (not mapped or override != ''),
                    'installed': installed, 'package': package,
                    'port': port,
                    'skipped_reason': None,
                    '_run_args': {'command': command,
                                  'name': f'ai-{tool_id}',
                                  'tabTitle': f'AI: {tool_id} ({port}/{protocol})',
                                  'hostIp': host_ip, 'port': str(port),
                                  'protocol': protocol, 'outputfile': outputfile,
                                  'run_actions': False},
                })
            idx += 1

        for sc in safe_commands:
            cmd_raw = sc.get('command', '')
            valid, reason = _validate_safe_command(cmd_raw)
            if not valid:
                proposed.append({
                    'index': idx, 'tool_id': 'safe_command',
                    'command': cmd_raw,
                    'rationale': sc.get('rationale', ''),
                    'source': 'safe_command',
                    'is_override': False,
                    'installed': True, 'package': '',
                    'port': '',
                    'skipped_reason': f'rejected: {reason}',
                })
            else:
                from app.timing import getTimestamp
                sc_name = os.path.basename(cmd_raw.split()[0])
                # Extract port from the command if present (e.g., http://IP:8080/...)
                sc_port = ''
                import re as _re
                _port_m = _re.search(r':(\d{2,5})[/\s]', cmd_raw)
                if _port_m:
                    sc_port = _port_m.group(1)
                outputfile = os.path.join(running_folder,
                                          f"{getTimestamp()}-ai-safe-{sc_name}-{host_ip}-{sc_port or '0'}")
                command = (cmd_raw
                           .replace('[IP]', host_ip)
                           .replace('[PORT]', sc_port)
                           .replace('[OUTPUT]', outputfile))
                binary, installed, package = _check_tool_installed(command)
                if sc_port:
                    # Extract a path or differentiator from the URL (e.g., /robots.txt)
                    _path_m = _re.search(r'https?://[^/\s]+(/[^\s"\']{1,30})', command)
                    _path_hint = _path_m.group(1) if _path_m else ''
                    sc_tab = f'AI: {sc_name} ({sc_port}/tcp{_path_hint})'
                else:
                    # Build a short descriptor from the command args (skip binary, IPs, flags)
                    _args = [a for a in cmd_raw.split()[1:]
                             if not a.startswith('-') and a not in ('[IP]', '[PORT]', '[OUTPUT]', host_ip)
                             and not a.startswith('/')]
                    sc_hint = ' '.join(_args)[:30].strip() if _args else host_ip
                    sc_tab = f'AI: {sc_name} ({sc_hint})'
                proposed.append({
                    'index': idx, 'tool_id': sc_name,
                    'command': command,
                    'rationale': sc.get('rationale', ''),
                    'source': 'safe_command',
                    'is_override': False,
                    'installed': installed, 'package': package,
                    'port': sc_port,
                    'skipped_reason': None,
                    '_run_args': {'command': command, 'name': f'ai-{sc_name}',
                                  'tabTitle': sc_tab,
                                  'hostIp': host_ip, 'port': sc_port,
                                  'protocol': 'tcp', 'outputfile': outputfile,
                                  'run_actions': False},
                })
            idx += 1

        job['proposed_commands'] = proposed

        # ── Step 2.5: Batch approval ─────────────────────────────────
        if proposed and any(p['skipped_reason'] is None for p in proposed):
            job['step'] = 'awaiting_approval'
            job['status'] = 'awaiting_approval'
            _job_progress(job, f'Waiting for user approval of {len(proposed)} commands...')

            evt = _job_approval_events.get(job_id)
            if evt:
                evt.wait()

            approved_indices = set(job.get('approved_commands', []))
            install_list = job.get('install_tools', [])

            # Install requested tools
            for pkg in install_list:
                _job_progress(job, f'Installing {pkg}...')
                try:
                    install_result = wc.runCommand(
                        command=f'apt-get install -y {pkg}',
                        name=f'install-{pkg}',
                        tabTitle=f'Installing {pkg}',
                        hostIp='', port='', run_actions=False,
                    )
                    install_pid = install_result.get('process_id')
                    if install_pid:
                        rc = logic.activeProject.repositoryContainer
                        for _ in range(120):
                            time.sleep(2)
                            try:
                                p = rc.processRepository.getProcessById(install_pid)
                                if p and p.get('status') not in ('Running', 'Waiting'):
                                    break
                            except Exception:
                                break
                    _job_progress(job, f'{pkg} installation complete')
                except Exception as e:
                    _job_progress(job, f'{pkg} installation failed: {e}')

            if not approved_indices:
                _job_progress(job, 'User skipped all commands')
        else:
            approved_indices = set()
            _job_progress(job, 'No valid commands to approve — skipping to re-synthesis')

        # ── Step 3: Tool execution ───────────────────────────────────
        job['step'] = 'tool_execution'
        job['status'] = 'running'

        process_ids = []
        for p in proposed:
            if p['index'] not in approved_indices:
                continue
            if p.get('skipped_reason'):
                continue
            run_args = p.get('_run_args')
            if not run_args:
                continue

            _job_progress(job, f"Running {p['tool_id']}...")
            try:
                result = wc.runCommand(**run_args)
                pid = result.get('process_id')
                if pid:
                    process_ids.append(pid)
                    p['process_id'] = pid
                    p['execution_status'] = 'Running'
            except Exception as e:
                _job_progress(job, f"Failed to start {p['tool_id']}: {e}")
                p['execution_status'] = 'Failed'

        if process_ids:
            _job_progress(job, f'Waiting for {len(process_ids)} tools to complete...')
            rc = logic.activeProject.repositoryContainer
            pid_to_proposed = {}
            for p in proposed:
                pid = p.get('process_id')
                if pid:
                    pid_to_proposed[pid] = p

            deadline = time.monotonic() + _TOOL_EXEC_TIMEOUT
            while time.monotonic() < deadline:
                all_done = True
                for pid in process_ids:
                    try:
                        proc_data = rc.processRepository.getProcessById(pid)
                        status = proc_data.get('status', '') if proc_data else ''
                        if pid in pid_to_proposed:
                            pid_to_proposed[pid]['execution_status'] = status or 'Waiting'
                        if status in ('Running', 'Waiting'):
                            all_done = False
                    except Exception:
                        pass
                if all_done:
                    break
                time.sleep(2)

            finished = sum(1 for p in proposed
                           if p.get('execution_status') == 'Finished')
            _job_progress(job, f'Tool execution complete: {finished}/{len(process_ids)} finished')
        else:
            _job_progress(job, 'No tools to execute')

        # ── Step 4: Re-synthesis ─────────────────────────────────────
        job['step'] = 'resynthesis'
        _job_progress(job, 'Re-synthesizing with enriched data...')

        result2 = _assemble_host_data(logic, host_id)
        if result2:
            (host_obj2, host_ip2, os_family2, ports2, cves2, scripts2,
             note_text2, processes2, fingerprint2) = result2
            enriched_procs2 = _enrich_processes(processes2)
            prompt_text2 = _build_phase1_prompt(
                host_obj2, host_ip2, os_family2, ports2, cves2, scripts2,
                note_text2, enriched_procs2)

            resyn_system = _PHASE1_SYSTEM + _PHASE1_RESYNTHESIS_EXTRA

            _job_progress(job, f'Calling AI ({model}) for re-synthesis...')
            p1r_resp = client.messages.create(
                model=model, max_tokens=8192,
                system=resyn_system,
                messages=[{'role': 'user', 'content': prompt_text2}],
            )
            p1r_text = p1r_resp.content[0].text.strip()
            tin3, tout3, cost3 = _actual_cost(p1r_resp.usage)
            job['cost_breakdown']['resynthesis'] = {
                'tokens_in': tin3, 'tokens_out': tout3, 'cost': cost3,
            }

            try:
                final_findings = _parse_llm_json(p1r_text)
            except json.JSONDecodeError:
                final_findings = phase1_findings

            final_fingerprint = fingerprint2
        else:
            final_findings = phase1_findings
            final_fingerprint = fingerprint
            tin3 = tout3 = 0
            cost3 = 0.0

        phase1_json = json.dumps(final_findings, indent=2)

        # Enrich proposed items with tool output before final save
        rc = logic.activeProject.repositoryContainer
        for p in proposed:
            pid = p.get('process_id')
            if not pid:
                continue
            try:
                from sqlalchemy import text as _sqlt
                _s = rc.processRepository.dbAdapter.session()
                row = _s.execute(_sqlt(
                    'SELECT output FROM process_output WHERE processId = :pid'
                ), {'pid': int(pid)}).fetchone()
                _s.close()
                if row and row[0]:
                    p['output'] = str(row[0]).strip()[:4000]
            except Exception:
                pass

        enum_actions = {
            'proposed': [{k: v for k, v in p.items() if k != '_run_args'}
                         for p in proposed],
            'approved_indices': list(approved_indices),
            'obvious_attacks': obvious_attacks,
        }
        enum_json = json.dumps(enum_actions, indent=2)

        total_tin = tin1 + tin2 + tin3
        total_tout = tout1 + tout2 + tout3
        total_cost = round(
            total_tin / 1_000_000 * _INPUT_COST_PER_MTOK +
            total_tout / 1_000_000 * _OUTPUT_COST_PER_MTOK, 4)

        _job_progress(job, f'Re-synthesis complete: {len(final_findings)} findings')

        # ── Update the partial records saved after Step 2 ────────────
        if history_id:
            try:
                conn = history_db._get_conn()
                conn.execute(
                    "UPDATE ai_sessions SET phase1_json=?, tokens_input=?, "
                    "tokens_output=?, cost_usd=?, enum_actions_json=?, "
                    "fingerprint_json=? WHERE id=?",
                    (phase1_json, total_tin, total_tout, total_cost,
                     enum_json, json.dumps(final_fingerprint), history_id))
                conn.commit()
                conn.close()
            except Exception as e:
                log.error(f"[AI] Final history-DB update failed: {e}")

        if project_analysis_id:
            try:
                rc2 = logic.activeProject.repositoryContainer
                session_up = rc2.hostRepository.dbAdapter.session()
                from db.entities.ai_analysis import AiAnalysis
                row = session_up.query(AiAnalysis).filter_by(id=project_analysis_id).first()
                if row:
                    row.phase1_json = phase1_json
                    row.tokens_input = total_tin
                    row.tokens_output = total_tout
                    row.cost_usd = total_cost
                    row.enum_actions_json = enum_json
                    session_up.commit()
            except Exception as e:
                try:
                    session_up.rollback()
                except Exception:
                    pass
                log.error(f"[AI] Final project-DB update failed: {e}")
            finally:
                try:
                    session_up.close()
                except Exception:
                    pass

        log.info(f"[AI] Enhanced Phase 1 complete — host={host_ip} cost=${total_cost:.4f}")

        final_result = {
            'host_ip': host_ip,
            'fingerprint': final_fingerprint if result2 else fingerprint,
            'phase1_json': phase1_json,
            'phase2_markdown': None,
            'tokens_input': total_tin,
            'tokens_output': total_tout,
            'cost_usd': total_cost,
            'history_id': history_id,
            'project_analysis_id': project_analysis_id,
            'timestamp': ts,
            'gap_analysis_json': gap_json,
            'enum_actions_json': enum_json,
        }

        job['result'] = final_result
        job['status'] = 'completed'
        job['step'] = 'done'
        _job_progress(job, 'Phase 1 enhanced analysis complete')

    except Exception as e:
        log.error(f"[AI] Enhanced Phase 1 job {job_id} failed: {e}", exc_info=True)
        job['status'] = 'failed'
        job['error'] = str(e)
        _job_progress(job, f'Failed: {e}')


def estimate_cost_enhanced(text_length_chars):
    """Pre-flight cost estimate for the enhanced pipeline (3 LLM calls)."""
    est_tokens_input = text_length_chars // _CHARS_PER_TOKEN
    est_tokens_output = 1000
    single_cost = (est_tokens_input / 1_000_000 * _INPUT_COST_PER_MTOK +
                   est_tokens_output / 1_000_000 * _OUTPUT_COST_PER_MTOK)
    multiplier = 2.5  # synthesis + gap_analysis(0.5x) + re-synthesis(1x)
    return est_tokens_input, round(single_cost * multiplier, 4)


# ---------------------------------------------------------------------------
# Main analysis entry point (original — kept for legacy/sync fallback)
# ---------------------------------------------------------------------------

def run_analysis(logic, host_id):
    """
    Run Phase 1 + Phase 2 for the given host_id.
    Returns a dict with all results or raises on error.
    Saves to both the persistent history DB and the project DB.
    """
    # Assemble data
    result = _assemble_host_data(logic, host_id)
    if result is None:
        raise ValueError(f"Host {host_id} not found in project DB")

    (host_obj, host_ip, os_family, ports, cves, scripts,
     note_text, processes, fingerprint) = result

    # getProcesses(showProcesses=True) already fetches output via LEFT JOIN
    # with process_output, so proc['output'] is already populated for finished
    # processes.  getProcessById returns no 'output' key and was overwriting
    # correct data with ''.  Fall back to the .live_output file for processes
    # that are still running or haven't saved to DB yet.
    rc = logic.activeProject.repositoryContainer
    enriched_procs = []
    for proc in processes:
        output = proc.get('output', '') or ''
        if not output.strip():
            outputfile = proc.get('outputfile', '')
            if outputfile:
                for suffix in ('.live_output', ''):
                    try_path = outputfile + suffix if suffix else outputfile
                    try:
                        with open(try_path, 'r', errors='replace') as _f:
                            output = _f.read()
                        if output.strip():
                            break
                    except Exception:
                        pass
        enriched_procs.append({**proc, 'output': output})

    # Build Phase 1 prompt
    prompt_text = _build_phase1_prompt(
        host_obj, host_ip, os_family, ports, cves, scripts,
        note_text, enriched_procs)

    config = _read_ai_config()
    model  = config['model']
    client = _get_client(config)

    total_tin = total_tout = 0

    # ── Phase 1 ─────────────────────────────────────────────────────────────
    log.info(f"[AI] Phase 1 starting for host {host_ip} (~{len(prompt_text)} chars)")
    p1_resp = client.messages.create(
        model=model,
        max_tokens=8192,
        system=_PHASE1_SYSTEM,
        messages=[{'role': 'user', 'content': prompt_text}]
    )
    p1_text = p1_resp.content[0].text.strip()
    tin, tout, _ = _actual_cost(p1_resp.usage)
    total_tin  += tin
    total_tout += tout

    # Parse Phase 1 JSON (be tolerant of markdown fences)
    phase1_json_str = p1_text
    if '```' in phase1_json_str:
        import re
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', phase1_json_str)
        if m:
            phase1_json_str = m.group(1).strip()
    try:
        phase1_findings = json.loads(phase1_json_str)
    except json.JSONDecodeError:
        log.warning(f"[AI] Phase 1 returned non-JSON; storing raw text")
        phase1_findings = [{'source': 'raw', 'port': None, 'severity': 'info',
                            'finding': p1_text[:500], 'evidence': ''}]
    phase1_json = json.dumps(phase1_findings, indent=2)

    # ── Phase 2 ─────────────────────────────────────────────────────────────
    log.info(f"[AI] Phase 2 starting for host {host_ip}")
    p2_resp = client.messages.create(
        model=model,
        max_tokens=8192,
        system=_PHASE2_SYSTEM,
        messages=[{'role': 'user',
                   'content': f"Host: {host_ip}\n\nFindings:\n{phase1_json}"}]
    )
    phase2_markdown = p2_resp.content[0].text.strip()
    tin, tout, _ = _actual_cost(p2_resp.usage)
    total_tin  += tin
    total_tout += tout
    total_cost  = round(
        total_tin  / 1_000_000 * _INPUT_COST_PER_MTOK +
        total_tout / 1_000_000 * _OUTPUT_COST_PER_MTOK, 4)

    # ── Persist to history DB ────────────────────────────────────────────────
    project_name = getattr(
        logic.activeProject, 'name',
        getattr(logic.activeProject, 'projectName', '')) or ''
    history_id = history_db.save_session(
        host_ip=host_ip,
        project_name=str(project_name),
        fingerprint=fingerprint,
        phase1_json=phase1_json,
        phase2_markdown=phase2_markdown,
        tokens_input=total_tin,
        tokens_output=total_tout,
        cost_usd=total_cost,
    )

    # ── Persist to project DB ────────────────────────────────────────────────
    ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    session = rc.hostRepository.dbAdapter.session()
    try:
        from db.entities.ai_analysis import AiAnalysis
        entry = AiAnalysis(
            host_id=int(host_id),
            timestamp=ts,
            phase1_json=phase1_json,
            phase2_markdown=phase2_markdown,
            tokens_input=total_tin,
            tokens_output=total_tout,
            cost_usd=total_cost,
            history_session_id=history_id,
        )
        session.add(entry)
        session.commit()
        project_analysis_id = entry.id
    except Exception as e:
        session.rollback()
        log.error(f"[AI] Failed to save to project DB: {e}")
        project_analysis_id = None
    finally:
        session.close()

    log.info(f"[AI] Complete — host={host_ip} cost=${total_cost:.4f} "
             f"tokens={total_tin}+{total_tout} history_id={history_id}")

    return {
        'host_ip':         host_ip,
        'fingerprint':     fingerprint,
        'phase1_json':     phase1_json,
        'phase2_markdown': phase2_markdown,
        'tokens_input':    total_tin,
        'tokens_output':   total_tout,
        'cost_usd':        total_cost,
        'history_id':      history_id,
        'project_analysis_id': project_analysis_id,
        'timestamp':       ts,
    }


def run_phase1(logic, host_id):
    """Run Phase 1 (synthesizer) only and save the result to the project DB.
    Phase 2 (attack planner) is left null — call run_phase2() separately."""
    result = _assemble_host_data(logic, host_id)
    if result is None:
        raise ValueError(f"Host {host_id} not found in project DB")
    (host_obj, host_ip, os_family, ports, cves, scripts,
     note_text, processes, fingerprint) = result

    rc = logic.activeProject.repositoryContainer
    enriched_procs = []
    for proc in processes:
        output = proc.get('output', '') or ''
        if not output.strip():
            outputfile = proc.get('outputfile', '')
            if outputfile:
                for suffix in ('.live_output', ''):
                    try_path = outputfile + suffix if suffix else outputfile
                    try:
                        with open(try_path, 'r', errors='replace') as _f:
                            output = _f.read()
                        if output.strip():
                            break
                    except Exception:
                        pass
        enriched_procs.append({**proc, 'output': output})

    prompt_text = _build_phase1_prompt(
        host_obj, host_ip, os_family, ports, cves, scripts,
        note_text, enriched_procs)

    config = _read_ai_config()
    model  = config['model']
    client = _get_client(config)

    log.info(f"[AI] Phase 1 starting for host {host_ip} (~{len(prompt_text)} chars)")
    p1_resp = client.messages.create(
        model=model, max_tokens=8192,
        system=_PHASE1_SYSTEM,
        messages=[{'role': 'user', 'content': prompt_text}]
    )
    p1_text = p1_resp.content[0].text.strip()
    tin, tout, _ = _actual_cost(p1_resp.usage)
    cost = round(tin / 1_000_000 * _INPUT_COST_PER_MTOK +
                 tout / 1_000_000 * _OUTPUT_COST_PER_MTOK, 4)

    # Parse JSON (tolerant of markdown fences)
    phase1_json_str = p1_text
    if '```' in phase1_json_str:
        import re as _re
        m = _re.search(r'```(?:json)?\s*([\s\S]*?)```', phase1_json_str)
        if m:
            phase1_json_str = m.group(1).strip()
    try:
        phase1_findings = json.loads(phase1_json_str)
    except json.JSONDecodeError:
        phase1_findings = [{'source': 'raw', 'port': None, 'severity': 'info',
                            'finding': p1_text[:500], 'evidence': ''}]
    phase1_json = json.dumps(phase1_findings, indent=2)

    # Persist Phase 1 to history DB (phase2_markdown=None for now;
    # run_phase2 will update it when the user requests the attack plan).
    project_name = getattr(
        logic.activeProject, 'name',
        getattr(logic.activeProject, 'projectName', '')) or ''
    try:
        history_id = history_db.save_session(
            host_ip=host_ip,
            project_name=str(project_name),
            fingerprint=fingerprint,
            phase1_json=phase1_json,
            phase2_markdown=None,
            tokens_input=tin,
            tokens_output=tout,
            cost_usd=cost,
        )
    except Exception as e:
        log.error(f"[AI] Phase 1 history-DB save failed: {e}")
        history_id = None

    # Persist Phase 1 to project DB
    ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    session = rc.hostRepository.dbAdapter.session()
    project_analysis_id = None
    try:
        from db.entities.ai_analysis import AiAnalysis
        entry = AiAnalysis(
            host_id=int(host_id), timestamp=ts,
            phase1_json=phase1_json, phase2_markdown=None,
            tokens_input=tin, tokens_output=tout, cost_usd=cost,
            history_session_id=history_id,
        )
        session.add(entry)
        session.commit()
        project_analysis_id = entry.id
    except Exception as e:
        session.rollback()
        log.error(f"[AI] Phase 1 project-DB save failed: {e}")
    finally:
        session.close()

    log.info(f"[AI] Phase 1 complete — host={host_ip} cost=${cost:.4f} "
             f"tokens={tin}+{tout}")
    return {
        'host_ip':             host_ip,
        'fingerprint':         fingerprint,
        'phase1_json':         phase1_json,
        'phase2_markdown':     None,
        'tokens_input':        tin,
        'tokens_output':       tout,
        'cost_usd':            cost,
        'history_id':          history_id,
        'project_analysis_id': project_analysis_id,
        'timestamp':           ts,
    }


def run_phase2(logic, host_id):
    """Run Phase 2 (attack planner) using the most recent Phase 1 result
    stored in the project DB for this host.  Updates the DB entry in place."""
    rc = logic.activeProject.repositoryContainer

    # Fetch most recent Phase 1 result
    session = rc.hostRepository.dbAdapter.session()
    try:
        from db.entities.ai_analysis import AiAnalysis
        entry = (session.query(AiAnalysis)
                 .filter_by(host_id=int(host_id))
                 .order_by(AiAnalysis.id.desc())
                 .first())
        if not entry or not entry.phase1_json:
            raise ValueError("No Phase 1 result found — run Phase 1 first")
        phase1_json      = entry.phase1_json
        gap_analysis_json = getattr(entry, 'gap_analysis_json', None) or ''
        enum_actions_json = getattr(entry, 'enum_actions_json', None) or ''
        entry_id    = entry.id
        prev_tin    = entry.tokens_input  or 0
        prev_tout   = entry.tokens_output or 0
        prev_cost   = entry.cost_usd      or 0.0
    finally:
        session.close()

    # Need host IP for the Phase 2 prompt
    result = _assemble_host_data(logic, host_id)
    if result is None:
        raise ValueError(f"Host {host_id} not found in project DB")
    host_ip = result[1]

    config = _read_ai_config()
    model  = config['model']
    client = _get_client(config)

    # Build Phase 2 prompt with gap analysis context for priority ranking
    p2_parts = [f"Host: {host_ip}", "", "=== FINDINGS ===", phase1_json]

    if gap_analysis_json:
        try:
            gap = json.loads(gap_analysis_json)
            obvious = gap.get('obvious_attacks', [])
            recommended = gap.get('recommended_tools', [])
            if obvious:
                p2_parts.append("")
                p2_parts.append("=== GAP ANALYSIS — OBVIOUS ATTACKS (confirmed, highest priority) ===")
                for a in obvious:
                    p2_parts.append(f"  [{a.get('severity', 'high')}] {a.get('attack', '')}")
                    if a.get('evidence'):
                        p2_parts.append(f"    Evidence: {a['evidence']}")
                    if a.get('next_command'):
                        p2_parts.append(f"    Command: {a['next_command']}")
            if recommended:
                p2_parts.append("")
                p2_parts.append("=== CONFIRMED BY TARGETED ENUMERATION ===")
                p2_parts.append("The following tools were specifically selected by AI gap analysis")
                p2_parts.append("to confirm suspected vulnerabilities. Their findings in the FINDINGS")
                p2_parts.append("section above should be treated as high-confidence:")
                for t in recommended:
                    p2_parts.append(f"  - {t.get('tool_id', '')} (port {t.get('port', 'N/A')}): {t.get('rationale', '')}")
        except (json.JSONDecodeError, TypeError):
            pass

    p2_content = '\n'.join(p2_parts)

    log.info(f"[AI] Phase 2 starting for host {host_ip}")
    p2_resp = client.messages.create(
        model=model, max_tokens=8192,
        system=_PHASE2_SYSTEM,
        messages=[{'role': 'user', 'content': p2_content}]
    )
    phase2_markdown = p2_resp.content[0].text.strip()
    tin, tout, _ = _actual_cost(p2_resp.usage)
    cost2 = round(tin / 1_000_000 * _INPUT_COST_PER_MTOK +
                  tout / 1_000_000 * _OUTPUT_COST_PER_MTOK, 4)

    # Update the project DB entry with Phase 2 results
    session2 = rc.hostRepository.dbAdapter.session()
    history_session_id = None
    try:
        from db.entities.ai_analysis import AiAnalysis
        entry2 = session2.query(AiAnalysis).filter_by(id=entry_id).first()
        if entry2:
            entry2.phase2_markdown = phase2_markdown
            entry2.tokens_input    = prev_tin  + tin
            entry2.tokens_output   = prev_tout + tout
            entry2.cost_usd        = round(prev_cost + cost2, 4)
            history_session_id     = entry2.history_session_id
            session2.commit()
    except Exception as e:
        session2.rollback()
        log.error(f"[AI] Phase 2 project-DB update failed: {e}")
    finally:
        session2.close()

    # Update history DB entry with phase2_markdown now that it is complete
    if history_session_id:
        try:
            conn = history_db._get_conn()
            conn.execute(
                "UPDATE ai_sessions SET phase2_markdown=?, tokens_input=?, "
                "tokens_output=?, cost_usd=? WHERE id=?",
                (phase2_markdown, prev_tin + tin, prev_tout + tout,
                 round(prev_cost + cost2, 4), history_session_id))
            conn.commit()
            conn.close()
            log.debug(f"[AI] Phase 2 history-DB updated (session {history_session_id})")
        except Exception as e:
            log.error(f"[AI] Phase 2 history-DB update failed: {e}")

    log.info(f"[AI] Phase 2 complete — host={host_ip} cost=${cost2:.4f} "
             f"tokens={tin}+{tout}")
    return {
        'phase2_markdown': phase2_markdown,
        'tokens_input':    tin,
        'tokens_output':   tout,
        'cost_usd':        cost2,
    }
