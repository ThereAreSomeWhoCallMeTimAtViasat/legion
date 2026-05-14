"""
AI History Database — persistent SQLite store for all AI analyses.

Lives at ~/.local/share/legion/ai_history.db (never deleted, survives
project switches). Every analyze call writes here; the project DB also
gets a copy linked by history_session_id.

Jaccard similarity is used to find past analyses for "similar" hosts:
  fingerprint = sorted list of "port/proto:service:version" tuples + OS family
  similarity  = |intersection| / |union|   threshold ≥ 0.95
"""

import json
import os
import sqlite3
import time
from datetime import datetime


_DB_PATH = os.path.expanduser('~/.local/share/legion/ai_history.db')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    host_ip         TEXT    NOT NULL,
    project_name    TEXT    NOT NULL DEFAULT '',
    fingerprint_json TEXT   NOT NULL,
    phase1_json     TEXT    NOT NULL,
    phase2_markdown TEXT    NOT NULL,
    tokens_input    INTEGER NOT NULL DEFAULT 0,
    tokens_output   INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL    NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_ai_host_ip ON ai_sessions(host_ip);
CREATE INDEX IF NOT EXISTS idx_ai_timestamp ON ai_sessions(timestamp);
"""


_MIGRATIONS = [
    "ALTER TABLE ai_sessions ADD COLUMN gap_analysis_json TEXT",
    "ALTER TABLE ai_sessions ADD COLUMN enum_actions_json TEXT",
]


def _get_conn():
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def build_fingerprint(ports_services, os_family=''):
    """
    Build a sorted list of 'port/proto:service:version' strings plus the OS.
    ports_services: list of dicts with keys port_number, protocol, service_name,
                    service_version (as returned by getPortsAndServicesByHostIP).
    Returns a sorted list of strings — the canonical fingerprint for Jaccard.

    Ephemeral ports (>32767) are excluded because RPC/NFS services bind to random
    high ports on each boot — including them tanks the Jaccard similarity between
    two scans of the same host even when the services are identical.
    """
    tuples = []
    for row in (ports_services or []):
        port    = str(row.get('portId') or row.get('port_number') or row.get('port') or '')
        proto   = str(row.get('protocol') or 'tcp')
        service = str(row.get('name') or row.get('service_name') or row.get('service') or '')
        version = str(row.get('version') or row.get('service_version') or '')
        if port:
            try:
                if int(port) > 32767:
                    continue   # skip ephemeral/dynamic ports
            except ValueError:
                pass
            tuples.append(f"{port}/{proto}:{service}:{version}")
    tuples.sort()
    if os_family:
        tuples.append(f"OS:{os_family}")
    return tuples


def jaccard(fp_a, fp_b):
    """Jaccard similarity between two fingerprint lists (as sets)."""
    a, b = set(fp_a), set(fp_b)
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def save_session(host_ip, project_name, fingerprint, phase1_json,
                 phase2_markdown, tokens_input, tokens_output, cost_usd,
                 gap_analysis_json=None, enum_actions_json=None):
    """Insert one AI session. Returns the new row id."""
    conn = _get_conn()
    ts = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    cur = conn.execute(
        """INSERT INTO ai_sessions
           (timestamp, host_ip, project_name, fingerprint_json,
            phase1_json, phase2_markdown, tokens_input, tokens_output, cost_usd,
            gap_analysis_json, enum_actions_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (ts, host_ip, project_name,
         json.dumps(fingerprint), phase1_json, phase2_markdown,
         tokens_input, tokens_output, cost_usd,
         gap_analysis_json, enum_actions_json))
    conn.commit()
    session_id = cur.lastrowid
    conn.close()
    return session_id


def find_similar(fingerprint, threshold=0.60, limit=10, current_host_ip=None):
    """
    Return a ranked list of sessions with Jaccard similarity ≥ threshold.
    Sessions for the same IP as current_host_ip are always included regardless
    of threshold — they are the most directly relevant comparisons.
    Each entry: {id, timestamp, host_ip, project_name, similarity,
                 os_family, port_count, phase1_json, phase2_markdown,
                 tokens_input, tokens_output, cost_usd}
    Sorted by same-IP first, then by similarity desc.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM ai_sessions ORDER BY timestamp DESC").fetchall()
    conn.close()

    fp_set = set(fingerprint)
    results = []
    seen_ids = set()
    for row in rows:
        try:
            stored = json.loads(row['fingerprint_json'])
        except Exception:
            continue
        sim = jaccard(fp_set, set(stored))
        same_ip = (current_host_ip and row['host_ip'] == current_host_ip)
        # Always include same-IP sessions; require threshold for cross-IP matches
        if sim >= threshold or same_ip:
            # Extract OS and port count from stored fingerprint
            os_family   = next((t.replace('OS:', '') for t in stored if t.startswith('OS:')), '')
            port_count  = sum(1 for t in stored if not t.startswith('OS:'))
            results.append({
                'id':             row['id'],
                'timestamp':      row['timestamp'],
                'host_ip':        row['host_ip'],
                'project_name':   row['project_name'],
                'similarity':     round(sim * 100, 1),
                'os_family':      os_family,
                'port_count':     port_count,
                'phase1_json':    row['phase1_json'],
                'phase2_markdown': row['phase2_markdown'],
                'tokens_input':   row['tokens_input'],
                'tokens_output':  row['tokens_output'],
                'cost_usd':       row['cost_usd'],
            })

    # Sort: same-IP sessions first (pinned at top), then by similarity desc
    results.sort(key=lambda x: (
        0 if (current_host_ip and x['host_ip'] == current_host_ip) else 1,
        -x['similarity'],
        x['timestamp']
    ))
    return results[:limit]


def get_session(session_id):
    """Fetch a single history session by id."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM ai_sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
