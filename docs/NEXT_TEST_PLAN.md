# Legion Flask — Next Test Phase Plan

**Status:** Planned — not yet implemented
**Baseline:** v7.6-flask — 609 tests passing (502 unit + 92 Selenium offline + 15 Selenium live)

---

## Two goals

1. **Multi-host data isolation** — prove data is tied to each individual host and never bleeds
2. **Gap automation** — automate the functional gaps left by the existing Selenium suite

---

## Part 1: Multi-Host Data Isolation

### Why this matters

The most critical correctness property of Legion: clicking host A shows host A's data; clicking host B shows host B's data. No data bleeds between hosts. The current Selenium suite only ever has one real host in the UI at a time.

### Seed data

Two distinct hosts with deliberately different data:

```
Host A: 10.20.30.1  OS: Linux 4.x
  ports: 22/tcp ssh, 80/tcp http
  note:  "host-a-note"
  process: echo "host-a-output"

Host B: 10.20.30.2  OS: Windows 10
  ports: 443/tcp https, 3389/tcp rdp
  note:  "host-b-note"
  process: echo "host-b-output"
```

### New file: `tests/test_selenium_multihost.py`

#### Panel isolation — selecting a host changes all data

| Test | Verifies |
|------|---------|
| `test_hosts_panel_shows_both` | Both rows in Hosts table |
| `test_select_a_ports_correct` | Host A → Services tab shows 22, 80 only |
| `test_select_b_ports_correct` | Host B → Services tab shows 443, 3389 only |
| `test_switch_a_to_b_ports_change` | Select A then B → ports update to B's |
| `test_switch_b_to_a_ports_change` | Select B then A → ports back to A's |
| `test_select_a_info_shows_a_ip` | Information tab shows 10.20.30.1, not 10.20.30.2 |
| `test_select_b_info_shows_b_ip` | Information tab shows 10.20.30.2, not 10.20.30.1 |
| `test_select_a_os_is_linux` | Information tab shows "Linux", not "Windows" |
| `test_select_b_os_is_windows` | Information tab shows "Windows", not "Linux" |

#### Notes isolation — notes are per-host

| Test | Verifies |
|------|---------|
| `test_host_a_notes_visible` | Select A → Notes tab contains "host-a-note" |
| `test_host_b_notes_visible` | Select B → Notes tab contains "host-b-note" |
| `test_host_a_note_absent_from_b` | Select A → Notes tab does NOT contain "host-b-note" |
| `test_host_b_note_absent_from_a` | Select B → Notes tab does NOT contain "host-a-note" |
| `test_write_note_on_a_not_visible_on_b` | Type note on A, switch to B → B notes unchanged |
| `test_switch_back_preserves_a_note` | Write note on A, switch to B, switch back → A note intact |

#### Dynamic tab isolation — process tabs are per-host

| Test | Verifies |
|------|---------|
| `test_host_a_tabs_show_only_a_process` | Select A → only host-a-output tab in right panel |
| `test_host_b_tabs_show_only_b_process` | Select B → only host-b-output tab in right panel |
| `test_tabs_change_on_host_switch` | Select A (A tab), select B (B tab), select A (A tab again) |
| `test_process_output_matches_host` | Click A's process tab → output has "host-a-output", not "host-b-output" |

#### Tab indicator isolation — orange is per-host

| Test | Verifies |
|------|---------|
| `test_orange_clears_when_switching_hosts` | Select A (orange appears), click tab (clears), select B, select A → not re-oranged |
| `test_b_data_change_doesnt_orange_a_tabs` | Trigger data change on B → select A → A's tabs are not orange |

#### OS tab isolation

| Test | Verifies |
|------|---------|
| `test_os_tab_lists_both_os` | OS tab shows both "Linux 4.x" and "Windows 10" |
| `test_os_linux_click_shows_host_a_only` | Click "Linux" → only 10.20.30.1 in host list |
| `test_os_windows_click_shows_host_b_only` | Click "Windows 10" → only 10.20.30.2 in host list |

#### API-level isolation — unit tests (no browser)

New file: `tests/test_multihost_isolation.py`

| Test | Verifies |
|------|---------|
| `test_snapshot_ports_belong_to_correct_host` | Port 22 in snapshot is linked to 10.20.30.1, not 10.20.30.2 |
| `test_ports_for_host_a_dont_include_b_ports` | getPortsByHostId(A) returns {22,80}, not {443,3389} |
| `test_ports_for_host_b_dont_include_a_ports` | getPortsByHostId(B) returns {443,3389}, not {22,80} |
| `test_note_saved_to_a_not_readable_on_b` | POST note to host A → GET host B information → note absent |
| `test_processes_in_snapshot_show_correct_host` | snapshot processes each have correct hostIp field |

---

## Part 2: Gap Automation

Gaps categorised by what kind of test is appropriate:

- **A — Selenium**: action produces a DOM-visible result
- **B — API test**: action produces a server-side verifiable result (Flask test client)
- **C — Manual only**: requires real external tools, network, or clipboard

---

### Category A — Selenium

New file: `tests/test_selenium_gaps.py`

#### File → Save + Open (project round-trip) ★ most important

The file browser (`#file-browser-modal`) is a custom DOM modal — not a native OS dialog. It calls `/api/files/browse` to list files and returns a path. Save and open are plain API calls (`/api/project/save-as`, `/api/project/open`). Fully automatable.

```
Approach — Selenium layer (full UI round-trip):
  1. Seed a host with ports and a note via the existing conftest mechanism
  2. File → Save:
     a. execute_script click on action-save (in File dropdown)
     b. file-browser-modal opens
     c. Type "/tmp/legion-selenium-test" in #fb-filename
     d. Click #fb-select
     e. Modal closes; #window-title contains the filename
  3. File → New:
     a. POST /api/project/new-temp directly (don't use Ctrl+N — resets session)
     b. Wait for snapshot poll
     c. Assert #hosts-body has 0 rows
  4. File → Open:
     a. execute_script click on action-open
     b. file-browser-modal opens
     c. Navigate to /tmp via #fb-path input
     d. Find and double-click "legion-selenium-test.legion" in #fb-list
     e. Modal closes; snapshot polls
     f. Assert original host row reappears
     g. Select host → Notes tab → assert original note text present
  5. Clean up /tmp/legion-selenium-test.legion

Assertions:
  - Host IP present in hosts table after open
  - Ports present in services tab after selecting host
  - Note text intact in notes tab
  - Window title shows project filename
```

#### File → New (clears project)

```
Approach:
  1. Confirm hosts exist in current session
  2. POST /api/project/new-temp
  3. Wait for snapshot poll (1.5s)
  4. Assert #hosts-body has 0 rows
  5. Assert #processes-body has 0 rows
```

#### Host delete

```
Approach:
  1. Seed two hosts A and B
  2. Right-click host A → Delete
  3. Browser confirm() appears → driver.switch_to.alert.accept()
  4. Wait for snapshot poll
  5. Assert host A row GONE from #hosts-body
  6. Assert host B row STILL present
```

#### Port double-click → switches left panel to Hosts tab

```
Approach:
  1. Select host → Services right tab → port rows visible
  2. Double-click a port row
  3. Assert #hosts-panel has 'active' class
  4. Assert left Services panel does NOT have 'active'
```

#### Send to Brute (port right-click)

```
Approach:
  1. Seed host with port 22/tcp ssh
  2. Select host → Services right tab → right-click port 22
  3. Context menu → click "Send to Brute"
  4. Assert main tab switches to brute-tab
  5. Assert #brute-ip value == host IP
  6. Assert #brute-port value == "22"
  7. Assert #brute-service value == "ssh"
```

#### Process → Kill

```
Approach:
  1. wc.runCommand('sleep 30', ...) from fixture
  2. Wait for status = Running in #processes-body
  3. Right-click row → Kill
  4. Wait for status to change (snapshot poll)
  5. Assert status is Killed or Finished (not Running)
```

#### Process → Retry

```
Approach:
  1. Use a Finished process (echo command from earlier test)
  2. Note current process count
  3. Right-click → Retry
  4. Assert row count increases (new process appeared)
  5. Assert new process reaches Finished
```

#### Process → Clear

```
Approach:
  1. Note process ID of a Finished process
  2. Right-click → Clear
  3. Wait for snapshot poll
  4. Assert tr[data-process-id="<id>"] is GONE from #processes-body
```

#### Filters modal

```
Approach:
  1. Seed Linux host and Windows host
  2. Open Filters modal (Filters button)
  3. Uncheck all OS types except Linux → Apply
  4. Assert only Linux host row in #hosts-body
  5. Assert Windows host row absent
  6. Open Filters modal → Reset → Apply
  7. Assert both hosts visible
```

#### Add Port modal

```
Approach:
  1. Select a host
  2. Right-click host row → Add Port
  3. add-port-modal opens
  4. Enter port=9999, protocol=tcp, service=test-service
  5. Submit
  6. Switch to Services right tab
  7. Assert row with port 9999 appears in #host-detail-ports
```

#### Notes save (same session)

```
Approach:
  1. Select host A
  2. Click Notes tab → type "selenium-unique-note-XYZ" in #notes-text
  3. Click host B (triggers auto-save on blur)
  4. Click back to host A
  5. Assert "selenium-unique-note-XYZ" visible in #notes-text or #notes-display
```

#### Column width resize persists across reload

```
Approach:
  1. Find .col-resize handle on hosts-table (first column)
  2. ActionChains: drag 60px to the right
  3. Read localStorage key via execute_script
  4. driver.refresh()
  5. Assert same localStorage value present after reload
  6. Assert column rendered at saved width
```

#### Screenshot modal (live scan only — add to TestLiveScan)

```
Approach:
  1. After screenshooter process Finished
  2. Click screenshooter dynamic tab → screenshot image appears in tab
  3. Click the screenshot image/thumbnail
  4. Assert #screenshot-modal has 'is-open' class
  5. Assert #screenshot-modal-image naturalWidth > 0
```

---

### Category B — API tests

New file: `tests/test_api_gaps.py` (uses Flask test client, no browser)

#### Project save → new → open (data integrity)

```python
def test_round_trip_preserves_hosts():
    # Save
    hosts_before = [h['ip'] for h in client.get('/api/snapshot').json['hosts']]
    client.post('/api/project/save-as', json={'path': '/tmp/rt-test.legion'})
    # New
    client.post('/api/project/new-temp')
    assert client.get('/api/snapshot').json['hosts'] == []
    # Open
    client.post('/api/project/open', json={'path': '/tmp/rt-test.legion'})
    hosts_after = [h['ip'] for h in client.get('/api/snapshot').json['hosts']]
    assert sorted(hosts_before) == sorted(hosts_after)
    os.unlink('/tmp/rt-test.legion')

def test_round_trip_preserves_ports():
    # Save current project, open fresh, verify ports still there
    ...

def test_round_trip_preserves_notes():
    # Write note, save, new, open, verify note text still present
    # Note: host ID may change after open — query by IP
    ...
```

#### Notes persist in DB (same session, no restart)

```python
def test_notes_saved_to_db():
    host_id = first_host_id()
    client.post(f'/api/workspace/hosts/{host_id}/note', json={'note': 'persist-test'})
    info = client.get(f'/api/workspace/hosts/{host_id}/information').json
    assert 'persist-test' in (info.get('note') or '')
```

#### Host delete removes from DB

```python
def test_delete_removes_host_from_db():
    hosts = client.get('/api/snapshot').json['hosts']
    host_id = hosts[0]['id']
    host_ip = hosts[0]['ip']
    client.post(f'/api/workspace/hosts/{host_id}/action', json={'action': 'delete'})
    remaining = [h['ip'] for h in client.get('/api/snapshot').json['hosts']]
    assert host_ip not in remaining
    # Verify other hosts unaffected
    for h in hosts[1:]:
        assert h['ip'] in remaining
```

#### Process Kill terminates the subprocess

```python
def test_kill_terminates_subprocess():
    result = wc.runCommand('sleep 30', name='kill-test', hostIp='10.20.30.1')
    pid = result['process_id']
    time.sleep(0.5)
    popen = get_active_popen(pid)   # from wc._active_processes
    client.post(f'/api/processes/{pid}/kill', json={})
    time.sleep(0.5)
    assert popen.poll() is not None  # process has exited
```

#### Export JSON has correct content

```python
def test_export_json_contains_all_hosts():
    r = client.get('/api/export/json')
    assert r.status_code == 200
    data = r.json
    ips = [h['ip'] for h in data.get('hosts', [])]
    assert '10.20.30.1' in ips
    assert '10.20.30.2' in ips

def test_export_json_contains_ports():
    data = client.get('/api/export/json').json
    all_ports = [p for h in data['hosts'] for p in h.get('ports', [])]
    port_nums = [p['port'] for p in all_ports]
    assert 22 in port_nums
    assert 443 in port_nums
```

---

### Category C — Manual only

| Feature | Why manual |
|---------|-----------|
| File → Export JSON **download** | Blob download doesn't write to disk in headless Firefox. Content verified via API (Category B above). |
| Ctrl+B Send selection to notes | Requires programmatic text selection across browser selection APIs — unreliable in headless mode. |
| Run Hydra | Requires real target with weak credentials + wordlists + minutes of runtime. |
| CVE detail / mark reviewed | Requires real CVE data from a live NSE scan. Tested during live scan session. |
| Screenshot image content | Whether the screenshot shows the right web page requires visual inspection. PNG loads confirmed by naturalWidth (already in live tests). |
| IPv6 scan | Requires IPv6-capable network and target. |
| Custom nmap scan modes | Hard/FIN/NULL/Xmas require network access, can't verify without real target. |

---

## Implementation Order

### Phase 1 — Project save/open ★ (highest risk if broken)
1. `tests/test_api_gaps.py` — round-trip: save → new → open preserves hosts, ports, notes
2. `tests/test_selenium_gaps.py::TestProjectFiles` — Selenium UI round-trip via file browser modal
3. `TestProjectFiles::test_file_new_clears_project` — new project empties hosts table

### Phase 2 — Multi-host isolation (catches data bleed bugs)
1. `tests/test_multihost_isolation.py` — ~5 API-level isolation tests
2. `tests/test_selenium_multihost.py` — ~22 Selenium isolation tests
3. Extend `conftest.py` seed data to two distinct hosts

### Phase 3 — Host/process actions (common workflows)
1. `tests/test_selenium_gaps.py::TestHostActions` — delete, add port, filters
2. `tests/test_selenium_gaps.py::TestProcessActions` — kill, retry, clear
3. `tests/test_selenium_gaps.py::TestPortActions` — double-click, send to brute

### Phase 4 — Notes, persistence, column resize
1. `tests/test_selenium_gaps.py::TestNotes` — write note, switch host, switch back
2. `tests/test_api_gaps.py::TestPersistence` — notes in DB, config save
3. `tests/test_selenium_gaps.py::TestColumnResize` — drag + reload + localStorage

### Phase 5 — Live scan additions
1. Add to `TestLiveScan`: screenshot modal click, CVE row count > 0, scripts tab has rows

---

## Expected test count after all phases

| Suite | Current | After all phases |
|-------|---------|-----------------|
| Unit tests | 502 | ~520 |
| Selenium offline | 92 | ~150 |
| Selenium live | 15 | ~20 |
| **Total** | **609** | **~690** |
