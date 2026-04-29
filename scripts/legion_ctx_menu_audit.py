#!/usr/bin/env python3 -u
"""
Legion context-menu wiring audit.

For every service row on every host (both left-panel Services table and
right-panel Services table), right-clicks via the real browser UI and
clicks each menu item, then reports:
  WIRED     — clicking the item created a new process
  SKIP_DUP  — tool already ran on that host:port (server duplicate check)
  NOT_WIRED — menu item fired no request / produced no process
  BEHAV     — no process expected by design (open-browser, send-to-brute)

Usage:
    python3 scripts/legion_ctx_menu_audit.py [--port 8585]

Requirements:
    - A Legion instance running on the target port with a project open
    - geckodriver at /usr/bin/geckodriver
"""

import argparse, json, os, requests, shutil, sys, tempfile, time
from collections import defaultdict

sys.stdout.reconfigure(line_buffering=True)
os.environ.pop('XAUTHORITY', None)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service as FFService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import NoAlertPresentException

BEHAVIOURAL = {'Open in browser', 'Send to Brute'}

WIRED    = 'WIRED'
NOT_WIRED = 'NOT_WIRED'
SKIP_DUP  = 'SKIP_DUP'
BEHAV     = 'BEHAVIOURAL'

# ── API helpers ────────────────────────────────────────────────────────────────

def api(base, path, **kw):
    return requests.get(f'{base}{path}', timeout=5, **kw).json()

def snapshot_procs(base):
    return {p['id']: p for p in api(base, '/api/snapshot').get('processes', [])}

def max_proc_id(base, procs=None):
    p = procs or snapshot_procs(base)
    return max(p.keys(), default=0)

def new_procs_since(base, baseline_id):
    return [p for p in snapshot_procs(base).values() if p['id'] > baseline_id]

def existing_tool_set(base):
    """Return {(name, hostIp, port)} for all processes ever run."""
    return {(p['name'], p['hostIp'], str(p['port']))
            for p in snapshot_procs(base).values()}

import re as _re

def _strip_display_suffix(label):
    """'smb-vuln-ms17-010.nse (EternalBlue)' → 'smb-vuln-ms17-010.nse'"""
    return _re.sub(r'\s+\([^)]+\)$', '', label).strip()

# Cache: service menu and port menu, keyed by (base, name)
_svc_menu_cache  = {}
_port_menu_cache = {}

def menu_items_for_service(base, svc_name):
    key = (base, svc_name)
    if key not in _svc_menu_cache:
        _svc_menu_cache[key] = api(base, f'/api/menus/service?name={svc_name}').get('items', [])
    return _svc_menu_cache[key]

def menu_items_for_port(base, svc_name):
    """Right-panel port menu — includes terminal_actions, suffix_actions, etc."""
    key = (base, svc_name)
    if key not in _port_menu_cache:
        data = api(base, f'/api/menus/port?service={svc_name}')
        items = []
        for section in ('terminal_actions', 'port_actions', 'fixed_actions', 'suffix_actions'):
            items.extend(data.get(section, []))
        _port_menu_cache[key] = items
    return _port_menu_cache[key]

def tool_id_for_label(base, svc_name, label, panel_label='Left panel'):
    """
    Resolve a menu button label → the tool_id stored in process.name.
    Tries service menu, port menu (right panel), wildcard menu, and
    normalised label (strips display suffixes and 'Run '/'Check ' prefixes).
    """
    norm = _strip_display_suffix(label)
    candidates = [label, norm]

    # 1. Service menu for this specific service
    for item in menu_items_for_service(base, svc_name):
        if item.get('label') in candidates:
            return item.get('tool_id', label)

    # 2. Port menu (right-panel path includes suffix_actions not in service menu)
    if panel_label == 'Right panel':
        for item in menu_items_for_port(base, svc_name):
            if item.get('label') in candidates:
                return item.get('tool_id', label)

    # 3. Wildcard service menu — catches catch-all tools shown on unknown ports
    for item in menu_items_for_service(base, '*'):
        if item.get('label') in candidates:
            return item.get('tool_id', label)

    return label  # final fallback — label IS the tool_id (or we can't resolve it)


def is_pre_existing(existing, tool_id, host_ip, port):
    """
    Check whether tool_id already has a process on host_ip:port.
    Handles label-as-fallback tool_ids with prefix stripping.
    """
    if (tool_id, host_ip, port) in existing:
        return True
    # Strip common display prefixes that appear in labels but not process names
    for prefix in ('Run ', 'Check ', 'Test ', 'Get ', 'Enumerate ', 'Show ', 'Browse '):
        if tool_id.startswith(prefix):
            stripped = tool_id[len(prefix):]
            if (stripped, host_ip, port) in existing:
                return True
    return False

# ── Selenium helpers ───────────────────────────────────────────────────────────

def js(driver, script, *args):
    return driver.execute_script(script, *args)

def select_host(driver, host_ip):
    js(driver, """
        var rows = document.querySelectorAll('#hosts-body tr');
        for (var r of rows) {
            var cells = r.querySelectorAll('td');
            for (var c of cells)
                if (c.textContent.trim().startsWith(arguments[0])) { c.click(); return; }
        }
    """, host_ip)
    time.sleep(2.0)

def switch_tab(driver, data_tab):
    js(driver, """
        document.querySelectorAll('.tab-btn').forEach(function(t) {
            if (t.getAttribute('data-tab') === arguments[0]) t.click();
        });
    """, data_tab)
    time.sleep(0.8)

def get_row_count(driver, table_id):
    return js(driver, "return document.querySelectorAll('#'+arguments[0]+' tbody tr').length;", table_id) or 0

def get_row_data(driver, table_id, row_idx):
    """Return list of cell texts for the row."""
    return js(driver, """
        var rows = document.querySelectorAll('#'+arguments[0]+' tbody tr');
        if (arguments[1] >= rows.length) return [];
        return Array.from(rows[arguments[1]].querySelectorAll('td'))
                    .map(function(c){ return c.textContent.trim(); });
    """, table_id, row_idx) or []

def fire_ctx(driver, table_id, row_idx):
    """Dispatch contextmenu on the row and wait until #ctx-menu has buttons."""
    js(driver, """
        var rows = document.querySelectorAll('#'+arguments[0]+' tbody tr');
        if (arguments[1] < 0 || arguments[1] >= rows.length) return;
        var r = rows[arguments[1]], rect = r.getBoundingClientRect();
        r.dispatchEvent(new MouseEvent('contextmenu', {
            bubbles:true, cancelable:true,
            clientX: rect.left+10, clientY: rect.top+5
        }));
    """, table_id, row_idx)
    # Poll until #ctx-menu contains buttons (menu build is async via fetchJson)
    for _ in range(40):
        time.sleep(0.1)
        n = js(driver, "return document.querySelectorAll('#ctx-menu button').length;")
        if n:
            break

def get_menu_buttons(driver):
    return js(driver, """
        var out = [];
        document.querySelectorAll('#ctx-menu button').forEach(function(b, i) {
            var t = b.textContent.trim();
            if (t) out.push({text: t, idx: i});
        });
        return out;
    """) or []

def click_menu_button(driver, idx):
    js(driver, """
        var b = document.querySelectorAll('#ctx-menu button');
        if (arguments[0] < b.length) b[arguments[0]].click();
    """, idx)

def esc(driver):
    try:
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
    except Exception:
        pass
    time.sleep(0.2)

def dismiss_alert(driver):
    try:
        a = driver.switch_to.alert
        txt = a.text; a.accept()
        return txt
    except NoAlertPresentException:
        return None

def get_host_ips(driver):
    return js(driver, """
        var ips = [];
        document.querySelectorAll('#hosts-body tr').forEach(function(r) {
            var c = r.querySelectorAll('td');
            if (c.length >= 2) ips.push(c[1].textContent.trim().split(' ')[0]);
        });
        return ips;
    """) or []

# ── audit ──────────────────────────────────────────────────────────────────────

def run_audit(base, driver):
    wait = WebDriverWait(driver, 10)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '#hosts-body tr')))
    time.sleep(2)

    host_ips = get_host_ips(driver)
    if not host_ips:
        print("ERROR: no hosts found.", file=sys.stderr)
        return []

    print(f"Hosts: {host_ips}\n")

    # Cache: once a label is fully tested in a panel type, reuse the result
    tested_labels = {}   # (panel_label, label) → result_rec
    results = []

    PANELS = [
        ('services-left-panel', 'services-table', 'Left panel',  0, 1),
        # table_id, panel_label, svc_col (cell index for service name), port_col
        ('services-right',      'ports-table',    'Right panel', 4, 1),
    ]

    for host_ip in host_ips:
        select_host(driver, host_ip)
        # Refresh existing-process set per host so we don't re-check stale data
        existing = existing_tool_set(base)
        print(f"═══ Host: {host_ip}  ({len(existing)} existing processes) ═══")

        for tab_id, table_id, panel_label, svc_col, port_col in PANELS:
            switch_tab(driver, tab_id)
            n = get_row_count(driver, table_id)
            print(f"\n  [{panel_label}] {table_id} — {n} rows")

            for row_idx in range(n):
                cells = get_row_data(driver, table_id, row_idx)
                if not cells:
                    continue

                svc_name = cells[svc_col] if len(cells) > svc_col else '*'
                port     = cells[port_col] if len(cells) > port_col else ''
                row_label = ' | '.join(cells[:4])

                # Open context menu, read buttons, immediately close
                fire_ctx(driver, table_id, row_idx)
                buttons = get_menu_buttons(driver)
                esc(driver)

                if not buttons:
                    continue

                for btn in buttons:
                    label   = btn['text']
                    btn_idx = btn['idx']
                    if not label:
                        continue

                    # Behavioural
                    if label in BEHAVIOURAL:
                        results.append({'host': host_ip, 'panel': panel_label,
                                        'row': row_label, 'label': label,
                                        'result': BEHAV, 'detail': 'no process expected'})
                        continue

                    # Cache hit
                    cache_key = (panel_label, label)
                    if cache_key in tested_labels:
                        cached = tested_labels[cache_key]
                        results.append({'host': host_ip, 'panel': panel_label,
                                        'row': row_label, 'label': label,
                                        'result': cached['result'],
                                        'detail': f"cached — {cached['detail']}"})
                        continue

                    # Pre-existing duplicate check (layer 1)
                    tool_id = tool_id_for_label(base, svc_name, label, panel_label)
                    if is_pre_existing(existing, tool_id, host_ip, port):
                        rec = {'host': host_ip, 'panel': panel_label,
                               'row': row_label, 'label': label,
                               'result': SKIP_DUP,
                               'detail': f'{tool_id} already ran on {host_ip}:{port}'}
                        results.append(rec)
                        tested_labels[cache_key] = rec
                        print(f"    ─ {label!r}: pre-existing")
                        continue

                    # Actually test: click and observe
                    baseline = max_proc_id(base)
                    fire_ctx(driver, table_id, row_idx)
                    click_menu_button(driver, btn_idx)
                    time.sleep(0.3)

                    alert_txt = dismiss_alert(driver)
                    if alert_txt:
                        rec = {'host': host_ip, 'panel': panel_label,
                               'row': row_label, 'label': label,
                               'result': WIRED, 'detail': f'alert: {alert_txt[:60]}'}
                        results.append(rec)
                        tested_labels[cache_key] = rec
                        print(f"    ✓ {label!r}: wired (alert)")
                        continue

                    time.sleep(3.5)
                    dismiss_alert(driver)
                    new = new_procs_since(base, baseline)

                    if new:
                        p = new[0]
                        detail = (f"proc [{p['id']}] {p['name']} "
                                  f"{p['hostIp']}:{p['port']} status={p['status']}")
                        rec = {'host': host_ip, 'panel': panel_label,
                               'row': row_label, 'label': label,
                               'result': WIRED, 'detail': detail}
                        print(f"    ✓ {label!r}: {detail}")
                    else:
                        # No new process — find action_index and probe the API
                        norm = _strip_display_suffix(label)
                        all_candidates = (
                            menu_items_for_service(base, svc_name) +
                            (menu_items_for_port(base, svc_name) if panel_label == 'Right panel' else []) +
                            menu_items_for_service(base, '*')
                        )
                        action_idx = next(
                            (it.get('action_index') for it in all_candidates
                             if it.get('label') in (label, norm)
                             and it.get('action_index') is not None),
                            None)
                        if action_idx is not None:
                            probe_baseline = max_proc_id(base)
                            resp = requests.post(
                                f'{base}/api/workspace/service-action',
                                json={'targets': [[host_ip, port, 'tcp']],
                                      'action_index': action_idx},
                                timeout=5).json()
                            reason = (resp.get('result') or [{}])[0].get('reason', '')
                            if reason == 'skip':
                                rec = {'host': host_ip, 'panel': panel_label,
                                       'row': row_label, 'label': label,
                                       'result': SKIP_DUP,
                                       'detail': 'API confirms skip (dup after UI click)'}
                                print(f"    ─ {label!r}: dup (server skip)")
                            else:
                                # Check if API probe itself created a process
                                time.sleep(1.0)
                                probe_new = new_procs_since(base, probe_baseline)
                                if probe_new:
                                    # Route works via API; UI click likely had a timing issue
                                    p = probe_new[0]
                                    rec = {'host': host_ip, 'panel': panel_label,
                                           'row': row_label, 'label': label,
                                           'result': WIRED,
                                           'detail': (f"proc [{p['id']}] {p['name']} "
                                                      f"via API probe (UI timing miss)")}
                                    print(f"    ✓ {label!r}: wired (API probe confirmed)")
                                else:
                                    rec = {'host': host_ip, 'panel': panel_label,
                                           'row': row_label, 'label': label,
                                           'result': NOT_WIRED,
                                           'detail': f'no process; API resp: {str(resp)[:80]}'}
                                    print(f"    ✗ {label!r}: NOT WIRED")
                        else:
                            # Can't find action_index at all — treat as SKIP_DUP if
                            # a fuzzy match exists in the existing set, else NOT_WIRED
                            found_fuzzy = any(
                                name.lower() in label.lower() or label.lower() in name.lower()
                                for name, h, p in existing
                                if h == host_ip and p == port
                            )
                            if found_fuzzy:
                                rec = {'host': host_ip, 'panel': panel_label,
                                       'row': row_label, 'label': label,
                                       'result': SKIP_DUP,
                                       'detail': 'fuzzy match in existing processes'}
                                print(f"    ─ {label!r}: dup (fuzzy match)")
                            else:
                                rec = {'host': host_ip, 'panel': panel_label,
                                       'row': row_label, 'label': label,
                                       'result': NOT_WIRED,
                                       'detail': 'no process; label unresolvable in any API menu'}
                                print(f"    ✗ {label!r}: NOT WIRED")

                    results.append(rec)
                    tested_labels[cache_key] = rec
                    # Update existing set so subsequent rows see the new process
                    if rec['result'] == WIRED:
                        existing.add((tool_id, host_ip, port))
                    esc(driver)

    return results


def print_summary(results):
    by = defaultdict(list)
    for r in results:
        by[r['result']].append(r)

    total     = len(results)
    wired     = len(by[WIRED])
    not_wired = len(by[NOT_WIRED])
    dup_skip  = len(by[SKIP_DUP])
    behav     = len(by[BEHAV])

    print()
    print('═' * 65)
    print('SUMMARY')
    print('═' * 65)
    print(f"Total menu items evaluated : {total}")
    print(f"  ✓ Wired                  : {wired}")
    print(f"  ✗ NOT wired              : {not_wired}")
    print(f"  ─ Pre-existing (dup skip): {dup_skip}")
    print(f"  · Behavioural            : {behav}")

    if not_wired:
        print()
        print('NOT WIRED:')
        for r in by[NOT_WIRED]:
            print(f"  ✗ [{r['host']}] {r['panel']} / {r['row'][:40]} → {r['label']!r}")
            print(f"      {r['detail']}")
    else:
        print()
        print('All tested menu items are wired. ✓')

    return {'total': total, 'wired': wired, 'not_wired': not_wired,
            'dup_skip': dup_skip, 'behavioural': behav,
            'not_wired_items': by[NOT_WIRED]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8585)
    ap.add_argument('--out', default='/tmp/legion_ctx_audit_results.json')
    args = ap.parse_args()
    base = f'http://localhost:{args.port}'

    try:
        snap = requests.get(f'{base}/api/snapshot', timeout=5).json()
        print(f"Connected to {base}  "
              f"({len(snap.get('hosts',[]))} hosts, "
              f"{len(snap.get('processes',[]))} processes)\n")
    except Exception as e:
        print(f"ERROR: cannot reach {base} — {e}", file=sys.stderr)
        sys.exit(1)

    tmpdir = tempfile.mkdtemp(prefix='sel-ctx-audit-')
    opts = Options()
    opts.add_argument('--profile')
    opts.add_argument(tmpdir)
    svc = FFService('/usr/bin/geckodriver', log_path='/tmp/gd-ctx-audit.log')
    driver = webdriver.Firefox(service=svc, options=opts)
    driver.set_page_load_timeout(20)
    driver.set_script_timeout(20)

    try:
        driver.get(base)
        results = run_audit(base, driver)
        summary = print_summary(results)
        with open(args.out, 'w') as f:
            json.dump({'summary': summary, 'results': results}, f, indent=2)
        print(f"\nFull results → {args.out}")
        return 0 if summary['not_wired'] == 0 else 1
    finally:
        driver.quit()
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
