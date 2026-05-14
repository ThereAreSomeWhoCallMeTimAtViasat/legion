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
import time
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
    "Be specific and actionable. Format your response in clear Markdown."
)


# ---------------------------------------------------------------------------
# Main analysis entry point
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
        phase1_json = entry.phase1_json
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

    log.info(f"[AI] Phase 2 starting for host {host_ip}")
    p2_resp = client.messages.create(
        model=model, max_tokens=8192,
        system=_PHASE2_SYSTEM,
        messages=[{'role': 'user',
                   'content': f"Host: {host_ip}\n\nFindings:\n{phase1_json}"}]
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
