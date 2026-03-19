# Legion Flask — Next Test Phase Plan

**Status:** Planned (not yet implemented)
**Depends on:** v7.6-flask, Selenium suite passing (609/609)

---

## Two goals

1. **Multi-host data isolation** — prove data is tied to each host and never bleeds between them
2. **Gap automation** — automate the 25+ functional gaps identified in TEST_PLAN.md

---

## Part 1: Multi-Host Data Isolation

### Why this matters

The most critical correctness property of Legion: when you click host A you see host A's data, and when you click host B you see host B's data. The current Selenium suite never tests two hosts simultaneously.

### Seed data needed

Two distinct hosts seeded in the test DB:

```
Host A: 10.20.30.1
  - ports: 22/tcp (ssh), 80/tcp (http)
  - OS: "Linux 4.x"
  - note: "host-a-note"
  - process: echo "host-a-output"

Host B: 10.20.30.2
  - ports: 443/tcp (https), 3389/tcp (rdp)
  - OS: "Windows 10"
  - note: "host-b-note"
  - process: echo "host-b-output"
```

### Tests to write: `tests/test_selenium_multihost.py`

#### Panel isolation — clicking host changes all data

| Test | What to verify |
|------|---------------|
| `test_hosts_panel_shows_both` | Both host rows appear in Hosts table |
| `test_select_a_ports_correct` | Click host A → Services tab shows ports 22, 80 only |
| `test_select_b_ports_correct` | Click host B → Services tab shows ports 443, 3389 only |
| `test_switch_a_to_b_ports_change` | Select A, then select B → ports table updates to B's ports |
| `test_switch_b_to_a_ports_change` | Select B, then select A → ports back to A's ports |
| `test_select_a_info_correct` | Information tab shows 10.20.30.1 (not 10.20.30.2) |
| `test_select_b_info_correct` | Information tab shows 10.20.30.2 (not 10.20.30.1) |
| `test_select_a_os_correct` | Information tab shows "Linux" (not "Windows") |
| `test_select_b_os_correct` | Information tab shows "Windows" (not "Linux") |

#### Notes isolation — notes are per-host

| Test | What to verify |
|------|---------------|
| `test_host_a_notes_visible` | Select host A → Notes tab shows "host-a-note" |
| `test_host_b_notes_visible` | Select host B → Notes tab shows "host-b-note" |
| `test_host_a_note_not_in_b` | Select host A → Notes tab does NOT contain "host-b-note" |
| `test_host_b_note_not_in_a` | Select host B → Notes tab does NOT contain "host-a-note" |
| `test_write_note_to_a_not_in_b` | Type new text in host A notes → switch to B → B notes unchanged |
| `test_switch_back_a_note_persists` | After writing host A note, switch to B, switch back to A → note still there |

#### Process / dynamic tab isolation — tabs are per-host

| Test | What to verify |
|------|---------------|
| `test_host_a_tabs_only_show_a_processes` | Select host A → only host-a-output process tab shown |
| `test_host_b_tabs_only_show_b_processes` | Select host B → only host-b-output process tab shown |
| `test_switch_host_tabs_change` | Select A (see A tab), select B (see B tab), select A (back to A tab) |
| `test_process_output_correct_for_host` | Click host A's process tab → output contains "host-a-output" not "host-b-output" |

#### Tab indicator isolation — orange is per-host

| Test | What to verify |
|------|---------------|
| `test_orange_clears_on_host_switch` | Select A (orange tabs appear) → click a tab (orange clears on A) → select B → select A again → orange not re-applied |
| `test_new_data_on_b_doesnt_orange_a_tabs` | Simulate port change on host B → select host A → A's tabs not orange |

#### OS tab isolation

| Test | What to verify |
|------|---------------|
| `test_os_groups_both_hosts` | OS tab lists both "Linux 4.x" and "Windows 10" |
| `test_os_click_shows_correct_host` | Click "Linux" in OS tab → only 10.20.30.1 in host list |
| `test_os_click_windows_shows_correct_host` | Click "Windows" → only 10.20.30.2 in host list |

#### Snapshot-level isolation (unit test, not Selenium)

| Test | File | What to verify |
|------|------|---------------|
| `test_getHostById_returns_correct_host` | `test_multihost_isolation.py` | getHostById(1) returns host A data, not host B |
| `test_ports_for_host_a_only` | same | getPortsByHostId(A) returns only A's ports |
| `test_ports_for_host_b_only` | same | getPortsByHostId(B) returns only B's ports |
| `test_notes_saved_per_host` | same | POST note to host A, GET host B → note absent |
| `test_processes_filtered_by_host` | same | snapshot processes for host A don't include host B processes |

---

## Part 2: Gap Automation

### Approach

Gaps split into three categories based on how they should be tested:

- **A — Fully automatable with Selenium**: action has a visible result in the DOM
- **B — Automatable with API verification**: action has a verifiable server-side result
- **C — Not practical to automate**: requires real external tools, real files, or clipboard

---

### Category A — Selenium (DOM result verifiable)

New test class: `TestHostActions` in `test_selenium_gaps.py`

#### Host delete

```
Approach:
  1. Seed two hosts (A and B) in test DB
  2. Right-click host A → click Delete → browser confirm() dialog appears
  3. Accept confirm() via driver.switch_to.alert.accept()
  4. Assert host A row gone from #hosts-body
  5. Assert host B row still present (delete didn't bleed)

Why automatable: confirm() is a real browser dialog; DOM row disappears after delete
```

#### Port double-click → switches to Hosts tab

```
Approach:
  1. Select a host → Services right tab active → port rows visible
  2. Double-click a port row
  3. Assert left panel switches: #hosts-panel has 'active' class
  4. Assert #services-left-panel does NOT have 'active'

Why automatable: tab switch is a CSS class change, detectable immediately
```

#### Send to Brute (port right-click)

```
Approach:
  1. Select host with SSH port (22/tcp) in seeded data
  2. Right-click port 22 row → context menu → click "Send to Brute"
  3. Assert main tab switches to Brute tab
  4. Assert #brute-ip value == host IP
  5. Assert #brute-port value == "22"
  6. Assert #brute-service value == "ssh"

Why automatable: all three fields and tab switch are DOM-verifiable
```

#### Process → Kill

```
Approach:
  1. Start a long-running process (e.g. 'sleep 30')
  2. Wait for status = Running
  3. Right-click process row → Kill
  4. Wait for status = Killed or Finished
  5. Assert status is NOT Running

Why automatable: status is a DOM cell that updates via snapshot poll
```

#### Process → Retry

```
Approach:
  1. Find a Finished process
  2. Right-click → Retry
  3. Assert a new process row appears (count increases)
  4. Assert new process eventually reaches Finished

Why automatable: row count change and status change are DOM-verifiable
```

#### Process → Clear

```
Approach:
  1. Find a Finished process, note its process ID
  2. Right-click → Clear
  3. Assert the row with that process ID is gone from #processes-body

Why automatable: row disappears from DOM after close
```

#### Filters modal — apply and verify

```
Approach:
  1. Seed two hosts: one Linux, one Windows
  2. Open Filters modal → check only Linux OS filter → Apply
  3. Assert only Linux host row visible in #hosts-body
  4. Assert Windows host row NOT in #hosts-body
  5. Clear/reset → assert both hosts visible again

Why automatable: host rows appear/disappear based on filter state
```

#### Add Port modal

```
Approach:
  1. Select a host
  2. Right-click host → Add Port (or from host context menu)
  3. Add-port-modal opens → enter port=9999, protocol=tcp, service=custom
  4. Submit
  5. Switch to Services right tab
  6. Assert port 9999 appears in #host-detail-ports

Why automatable: port row appears in DOM after save
```

#### Screenshot modal (thumbnail → full modal)

```
Approach:
  Only meaningful after live scan. Add to TestLiveScan:
  1. After screenshooter Finished, find screenshot element in dynamic tab
  2. Click it
  3. Assert screenshot-modal has 'is-open' class
  4. Assert #screenshot-modal-image has naturalWidth > 0

Why automatable: modal is DOM, image has naturalWidth
```

#### File → Save + Open (project round-trip)

This is the most important persistence test. The entire data model — hosts,
ports, services, notes, processes — must survive a save → new project → open cycle.

```
Approach (two layers):

Layer 1 — API (fast, no browser needed):
  1. Seed hosts, ports, notes into test DB
  2. POST /api/project/save-as  { path: "/tmp/test.legion" }
  3. POST /api/project/new-temp   (clears active project)
  4. Assert /api/snapshot returns 0 hosts (project is empty)
  5. POST /api/project/open  { path: "/tmp/test.legion" }
  6. Assert /api/snapshot returns original hosts + ports
  7. Assert notes still present via /api/workspace/hosts/<id>/information
  8. Clean up /tmp/test.legion

Layer 2 — Selenium (full UI round-trip via file browser modal):
  1. Add a host via UI, add a note via Notes tab
  2. File → Save → file-browser-modal opens
  3. Type filename in #fb-filename input → click #fb-select
  4. Modal closes, title bar shows filename
  5. File → New (via API: POST /api/project/new-temp + pollSnapshot)
  6. Assert Hosts table is empty
  7. File → Open → file-browser-modal opens
  8. Find the saved .legion file in #fb-list, double-click it
  9. Modal closes, pollSnapshot fires
  10. Assert original host row reappears
  11. Select host → Notes tab → assert note text still present
  12. Clean up saved file

Why automatable:
  - File browser is #file-browser-modal (DOM, not native OS dialog)
  - /api/files/browse lists directory, #fb-list contains clickable rows
  - Save/open are plain API POSTs; result is visible in snapshot
```

#### File → New (clears project)

```
Approach:
  1. Seed a host
  2. Trigger new project: POST /api/project/new-temp directly, or
     click action-new via execute_script
  3. Wait for snapshot poll
  4. Assert #hosts-body has 0 rows (project is empty)
  5. Assert #processes-body has 0 rows

Note: don't trigger via Ctrl+N keyboard shortcut in Selenium — it would
reset the shared test session. Use the API call directly.
```

#### Column width resize persists

```
Approach:
  1. Find hosts-table column resize handle
  2. ActionChains drag it 50px to the right
  3. Reload page (driver.refresh())
  4. Assert column is same width (from localStorage)

Why automatable: width stored in localStorage, CSS width is readable via JS
  driver.execute_script("return localStorage.getItem('col-hosts-table-0')")
```

#### Notes save and immediate re-read (same session)

```
Approach:
  1. Select host A
  2. Click Notes tab → type unique text ("selenium-note-test-XYZ")
  3. Click away (host B) to trigger auto-save
  4. Click back to host A
  5. Assert Notes tab contains "selenium-note-test-XYZ"

Why automatable: notes text is in a DOM element; switching hosts triggers save
Note: do NOT test across server restart here — that's Category B
```

#### Dynamic tab Save Output (blob download trigger)

```
Approach:
  Verify the mechanism fires; can't easily intercept blob download in headless.
  Alternative: verify via JS that the blob was created:
    driver.execute_script("""
      var a = document.querySelector('a[download]');
      return a ? a.download : 'no download triggered';
    """)
  Or: intercept with a network listener.

Verdict: Test that the click doesn't error and the menu item fires correctly.
Full download content verification: Category C.
```

---

### Category B — API verification (server-side result)

New test class: `TestAPIGaps` in `test_selenium_gaps.py` or standalone `test_api_gaps.py`

These use the Flask test client, not Selenium. They verify the server-side action completed correctly.

#### Notes persist across session (API level)

```python
def test_notes_persist_in_db(client, logic):
    # Save note via API
    host_id = get_first_host_id(logic)
    client.post(f'/api/workspace/hosts/{host_id}/note', json={'note': 'persist-test'})
    # Read it back via a fresh API call
    r = client.get(f'/api/workspace/hosts/{host_id}/information')
    assert 'persist-test' in r.get_json().get('note', '')
```

#### Config save writes to settings object

```python
def test_config_save_updates_settings(client):
    # POST to settings endpoint
    r = client.post('/api/settings/legion-conf', json={'text': '[GeneralSettings]\nenable-scheduler=False'})
    assert r.status_code == 200
    # Read back
    r2 = client.get('/api/settings/legion-conf')
    assert 'enable-scheduler=False' in r2.get_json().get('text', '')
```

#### Process Kill actually terminates subprocess

```python
def test_kill_terminates_popen(wc):
    import signal, time
    result = wc.runCommand('sleep 30', name='killtest', hostIp='10.20.30.1')
    pid = result['process_id']
    time.sleep(0.5)
    proc = get_process_by_id(pid)
    popen = proc._popen
    # Kill via API
    client.post(f'/api/processes/{pid}/kill', json={})
    time.sleep(0.5)
    assert popen.poll() is not None  # process has exited
```

#### Project save → new → open round-trip (data integrity)

```python
def test_save_open_round_trip(client, logic, filters):
    # Confirm hosts exist
    hosts_before = get_all_hosts(logic, filters)
    assert len(hosts_before) > 0

    # Save project to temp file
    save_path = '/tmp/selenium-test.legion'
    r = client.post('/api/project/save-as', json={'path': save_path})
    assert r.status_code == 200

    # New project — clears everything
    client.post('/api/project/new-temp')
    snap = client.get('/api/snapshot').get_json()
    assert len(snap['hosts']) == 0, "New project should be empty"

    # Open saved project
    r = client.post('/api/project/open', json={'path': save_path})
    assert r.status_code == 200

    # All original hosts present
    snap = client.get('/api/snapshot').get_json()
    opened_ips = [h['ip'] for h in snap['hosts']]
    for host in hosts_before:
        assert host['ip'] in opened_ips, f"{host['ip']} missing after open"

    os.unlink(save_path)

def test_save_open_preserves_notes(client, logic):
    host_id = get_first_host_id(logic)
    client.post(f'/api/workspace/hosts/{host_id}/note', json={'note': 'round-trip-note'})

    save_path = '/tmp/selenium-notes-test.legion'
    client.post('/api/project/save-as', json={'path': save_path})
    client.post('/api/project/new-temp')
    client.post('/api/project/open', json={'path': save_path})

    # Host IDs may change after open — find by IP
    snap = client.get('/api/snapshot').get_json()
    new_host_id = snap['hosts'][0]['id']
    info = client.get(f'/api/workspace/hosts/{new_host_id}/information').get_json()
    assert 'round-trip-note' in (info.get('note') or '')
    os.unlink(save_path)

def test_save_open_preserves_ports(client, logic, filters):
    save_path = '/tmp/selenium-ports-test.legion'
    client.post('/api/project/save-as', json={'path': save_path})
    client.post('/api/project/new-temp')
    client.post('/api/project/open', json={'path': save_path})

    snap = client.get('/api/snapshot').get_json()
    host_id = snap['hosts'][0]['id']
    r = client.get(f'/api/workspace/hosts/{host_id}')
    ports = r.get_json().get('ports', [])
    assert len(ports) > 0, "Ports not preserved after save/open"
    os.unlink(save_path)
```

#### Export JSON contains correct data

```python
def test_export_json_has_hosts(client, logic):
    r = client.get('/api/export/json')
    assert r.status_code == 200
    data = r.get_json()
    ips = [h['ip'] for h in data.get('hosts', [])]
    assert '10.20.30.1' in ips
    assert '10.20.30.2' in ips
```

#### Host delete removes from DB

```python
def test_delete_host_removes_from_db(client, logic, filters):
    host_id = get_host_id_by_ip(logic, '10.20.30.1', filters)
    client.post(f'/api/workspace/hosts/{host_id}/action', json={'action': 'delete'})
    hosts = get_all_hosts(logic, filters)
    ips = [h['ip'] for h in hosts]
    assert '10.20.30.1' not in ips
    assert '10.20.30.2' in ips  # other host unaffected
```

---

### Category C — Not practical to automate

These require real external tools, real filesystem paths the browser controls, or are fundamentally difficult to verify in headless mode:

| Feature | Why not automatable |
|---------|-------------------|
| File → Save / Open | ~~Moved to Category A and B~~ — the file browser is a custom DOM modal (not a native OS dialog) and the save/open routes are plain API calls. See below. |
| File → Export JSON download | Blob download in headless Firefox doesn't produce a file on disk accessible to test. Verify server-side via API (Category B). |
| Ctrl+B Send selection to notes | Requires text selection in the output panel, which is complex to reproduce programmatically across browser selection APIs. |
| Run Hydra | Requires real target with weak credentials, wordlists, minutes of runtime. Manual test against live VM. |
| CVE detail / mark reviewed | Requires real CVE data from NSE scan. Test in live scan context. |
| Screenshot image content | PNG loads confirmed by naturalWidth. Actual image content (correct URL, correct host) requires visual inspection or image comparison. |
| IPv6 scan | Requires IPv6-capable network and target. |
| Custom nmap scan modes | Hard mode, FIN/NULL/Xmas scans require network access and can't be verified without a real target. |
| Column resize drag precision | ActionChains drag is unreliable across window sizes. Verify localStorage key exists instead. |

---

## Implementation Order

### Phase 1 — Multi-host isolation (highest value, catches real bugs)
1. Add `tests/test_selenium_multihost.py` with ~20 isolation tests
2. Add unit test `tests/test_multihost_isolation.py` with ~5 API-level isolation tests
3. Extend `conftest.py` seed data to two distinct hosts with different ports/notes/processes

### Phase 2 — Host/process actions (medium value, covers common workflows)
1. Add `tests/test_selenium_gaps.py`
2. Implement in order: host delete → process kill/retry/clear → send to brute → port double-click → filters modal → add port modal → notes save

### Phase 3 — Persistence and API verification
1. Add `tests/test_api_gaps.py`
2. Implement: notes persist, config save, delete from DB, export JSON content

### Phase 4 — Live scan gaps (add to TestLiveScan)
1. Screenshot modal opens on click
2. CVE count > 0 after NSE (asserts actual data, not just tab renders)
3. Scripts tab has rows after scan

---

## Expected test count after all phases

| Suite | Current | After all phases |
|-------|---------|-----------------|
| Unit tests | 502 | ~520 |
| Selenium offline | 92 | ~145 |
| Selenium live | 15 | ~20 |
| **Total** | **609** | **~700** |
