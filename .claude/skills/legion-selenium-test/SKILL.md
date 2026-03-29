---
name: legion-selenium-test
description: Use this skill when the user asks to write a Selenium test for a Legion Flask UI feature, or invokes "/legion-selenium-test". Provides patterns and rules for non-hollow browser tests against the Legion web app.
argument-hint: <feature to test>
---

# Legion Selenium Test Writer

Write a non-hollow Selenium test for a Legion Flask UI feature using the patterns
from `tests/test_ui_session_features.py`.  The test must exercise real browser
behaviour — no mocking, no hollow assertions.

## What to test

$ARGUMENTS

## Rules — apply every one

**Server fixture (module-scoped)**
```python
@pytest.fixture(scope="module")
def srv():
    import app.web.routes as _web_routes
    _web_routes._HB_TIMEOUT = 600          # disable watchdog during tests
    _free_port(PORT)
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    from werkzeug.serving import make_server
    app, logic, wc = create_test_app()
    app.config['TESTING'] = False
    # seed a host
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output='')
    os.unlink(p)
    httpd = make_server('127.0.0.1', PORT, app, threaded=True)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start(); time.sleep(2.0)
    yield {'app': app, 'logic': logic, 'wc': wc, 'url': f'http://127.0.0.1:{PORT}'}
    httpd.shutdown()
    _web_routes._HB_TIMEOUT = 20
```

**Driver fixture (module-scoped)**
```python
@pytest.fixture(scope="module")
def drv(srv):
    import os as _os
    _os.environ.pop('XAUTHORITY', None); _os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions(); opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.set_script_timeout(30)    # prevents execute_script() hanging forever
    d.get(srv['url']); time.sleep(2.0)
    yield d
    d.quit()
```

**Port freeing helper — always include**
```python
def _free_port(port, retries=20):
    import subprocess, socket
    subprocess.run(['fuser', '-k', f'{port}/tcp'], capture_output=True)
    for _ in range(retries):
        try:
            s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port)); s.close(); return
        except OSError: time.sleep(0.5)
    raise RuntimeError(f"Port {port} still in use")
```

**Watchdog — always disable**
Set `_web_routes._HB_TIMEOUT = 600` before `create_test_app()`.  The default is
20 s; page reloads between tests create heartbeat gaps that kill the server.

**Heartbeat watchdog note** — `app.web.routes._HB_TIMEOUT` is read dynamically by
the watchdog thread on every check, so setting it on the module object before the
server starts (and restoring in teardown) is sufficient.

**DOM mutations — never innerHTML=''**
`element.innerHTML = ''` on a node with attached event listeners can hang Firefox
headless indefinitely (no timeout fires).  Instead, let the new content overwrite
the element naturally (e.g. click the new process row; `loadProcessOutput` replaces
the innerHTML for you).

**execute_script timeout**
Add `d.set_script_timeout(30)` in the driver fixture.  Without it, a hung JS call
blocks Selenium forever — the `WebDriverWait` timer only fires *after* the inner
call returns.

**Process completion — use API not DOM**
`#processes-body` can be suppressed by localStorage splitter widths from earlier
tests.  Use Python `requests` to poll `/api/snapshot` instead:
```python
def _wait_proc_done_api(srv_url, proc_id, timeout=25):
    import requests as _req
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for p in _req.get(f"{srv_url}/api/snapshot", timeout=5).json().get('processes', []):
                if str(p.get('id')) == str(proc_id) and p.get('status') in ('Finished','Killed','Crashed'):
                    return
        except Exception: pass
        time.sleep(0.5)
    raise TimeoutError(f"Process {proc_id} did not finish within {timeout}s")
```

**Find process rows by data-process-id, not text**
```python
proc_row = W(drv, 8).until(EC.presence_of_element_located(
    (By.CSS_SELECTOR, f'#processes-body tr[data-process-id="{proc_id}"]')))
```
Text-search (`cells[1].text contains name`) breaks when localStorage restores
splitter widths that reduce the table column to 0 px.

**Inject match data directly into wc._matches**
```python
wc._matches[f"{hostIp}:{tabTitle}"] = ['KEYWORD']
time.sleep(2.5)   # wait ≥1 snapshot cycle so L.processes picks up has_match=True
```
The snapshot route reads `wc._matches` synchronously; no conf editing needed.

**Class-scoped fixture for groups of tests sharing one page load**
When several tests operate on the same page state (e.g. match-nav tests all need
matchPositive injected and a host selected), use a class-scoped fixture to do
the page load ONCE.  Repeated `drv.get()` across 13 tests causes Firefox to
accumulate memory and eventually drop the geckodriver connection:
```python
@pytest.fixture(scope="class")
def my_setup(drv, srv):
    drv.get(srv['url']); time.sleep(1.5)
    _select_host(drv)
    js(drv, "matchPositive.push('KEYWORD')")
    yield
```
Each test in the class then just creates its unique process (unique `name=`) and
clicks its own row — `_matchNavState` is keyed by processId so there is no
cross-test state contamination.

**Stale WebElement — always re-find after sleeps**
The snapshot re-renders `#processes-body` every 1.5 s.  Any `WebElement` captured
before a 2.5 s sleep is stale by the time you click it.  Re-find by CSS selector
after the sleep.

**run_tests.sh integration**
Add to the `--selenium` section:
```bash
free_port PORT; run_pytest "test_name" tests/test_name.py
```
Add PORT to the initial cleanup loop:
```bash
for _p in PORT 5085 5086 ...; do free_port "$_p"; done
```

**Port assignment** — pick an unused port.  Current allocations:
5072 test_ui_session_features | 5083-5084 shutdown | 5085-5086 user-stories
5087-5091 goal tests | 5094-5099 selenium suites

## Color assertions — Firefox normalises hex to rgb()

`element.getAttribute('style')` returns browser-normalised CSS.  Firefox converts
shorthand hex colours like `#f44` to `rgb(255, 68, 68)` before storing them in the
style attribute, so string-matching `'color:#f44'` always fails.  Always accept
both forms with a helper:

```python
def _has_red(style):
    """Accept #f44 (source) or rgb(255, 68, 68) (Firefox-normalised)."""
    return (
        'color:#f44'         in style or
        'color: #f44'        in style or
        'rgb(255, 68, 68)'   in style
    )
```

Apply the same pattern to any hex colour your JS sets inline.  Compute the rgb()
equivalent with: `int('ff',16), int('44',16), int('44',16)` → `255, 68, 68`.

---

## Triggering File-menu actions without hover

The Legion file-menu dropdown is only visible on hover.  Selenium `.click()` on a
hidden dropdown item raises `ElementNotInteractableError`.  Bypass the dropdown
entirely by JS-clicking the action button directly — it exists in the DOM
regardless of whether the dropdown is visible:

```python
js(drv, "document.getElementById('action-save-as').click()")
```

Then wait for the modal to become visible before reading it:

```python
W(drv, 8).until(EC.visibility_of_element_located((By.ID, 'file-browser-modal')))
```

---

## Toggle-button state — reset before each test class

Buttons that store toggle state in `dataset.hidden` (e.g. Hide Finished / Hide All)
accumulate state across tests if not reset.  In the class fixture setup, force both
the DOM attribute and the label back to the initial state via JS, AND call the
restore API so the DB is clean too:

```python
requests.post(f"{srv['url']}/api/processes/restore", json={'reset_all': True})
js(drv, """
    var b = document.getElementById('process-clear-finished-button');
    if (b) { b.dataset.hidden = '0'; b.textContent = 'Hide Finished'; }
""")
```

Without this, a test that clicked "Hide Finished" but didn't click "Unhide Finished"
leaves the button in the toggled state, causing the next class's "initial label"
assertion to fail.

---

## Verifying hide/unhide by process ID, not row count

Never assert `len(rows) == 0` against the whole `#processes-body` — other tests
may have left Running or Waiting processes that are unaffected by "Hide Finished".
Always scope the check to the specific process ID you hid:

```python
# Absent after hide:
rows = drv.find_elements(By.CSS_SELECTOR,
    f'#processes-body tr[data-process-id="{proc_id}"]')
assert len(rows) == 0

# Present after unhide:
rows = drv.find_elements(By.CSS_SELECTOR,
    f'#processes-body tr[data-process-id="{proc_id}"]')
assert len(rows) == 1
```

---

## Verifying sort order — filter rows by data attribute suffix

When the tools table contains entries from multiple tests, don't check the order of
all rows — filter to only the rows your test created, using a suffix or prefix that
is unique to your test:

```python
def _sort_rows(drv):
    rows = drv.find_elements(By.CSS_SELECTOR, '#tools-body tr')
    return [
        r.get_attribute('data-tool-id')
        for r in rows
        if (r.get_attribute('data-tool-id') or '').endswith('-sorttest')
    ]
```

Submit the processes in deliberately reverse order (zzz → mmm → aaa) so that a
passing test proves the sort is active, not just reflecting insertion order.

---

## Additional patterns — save/open and DB-inspection tests

These lessons came from writing `tests/test_save_open_data.py` (v10.65–v10.66).
Apply them whenever a test calls `/api/project/save-as` or inspects the SQLite DB.

**Grep every route before using it**
Never assume a URL from the function name.
```bash
grep -n "@web_bp" app/web/routes.py | grep -i "<keyword>"
```
`nmap_scan()` lives at `/api/nmap/scan`, not `/api/workspace/hosts/add`.

**Name HTTP helper param `url`, not `path`**
```python
def _post(url, **kw):   # NEVER `def _post(path, **kw)`
    return requests.post(f"{BASE}{url}", json=kw, timeout=15)
```
If the param is named `path` and the JSON body also has a key `path` (e.g. the
save-as route), Python raises `TypeError: got multiple values for argument 'path'`.

**`saveProjectAs()` switches `logic.activeProject` — always reset afterward**
`/api/project/save-as` does not just copy the file; it makes the saved file the
active project. If you then delete it, SQLAlchemy silently recreates an empty DB
at that path (no ORM tables), breaking all subsequent tests.

Pattern: record the old folder before saving, check the saved file in tests, then
call `_reset_server(srv)` in class fixture teardown before deleting.

```python
def _reset_server(srv):
    """Undo the active-project switch that saveProjectAs() performs."""
    from app.importers.nmap_import import import_nmap_xml
    srv['wc'].killRunningProcesses()
    time.sleep(1.5)   # threads need time to see kill status before project switch
    srv['logic'].createNewTemporaryProject()
    srv['wc'].start()
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(SEED); p = f.name
    import_nmap_xml(project=srv['logic'].activeProject, xml_path=p, output='')
    os.unlink(p)

# In class fixture teardown:
yield
_reset_server(srv)
for p in [dest, dest+'-wal', dest+'-shm']:
    try: os.unlink(p)
    except: pass
```

**1.5s settle after `killRunningProcesses()` before switching projects**
Background nmap/capture threads wake from `proc._popen.wait()`, check kill status,
then exit. That check takes ~1s. Switch projects immediately and a thread will try
to `SELECT FROM process` on the new empty DB → `OperationalError: no such table`.

**`type(self)._var` to store data in class-scoped fixtures**
```python
@pytest.fixture(scope="class", autouse=True)
def setup(self, srv):
    type(self)._dest = save_something()   # set via type(self)
    yield
    cleanup(type(self)._dest)

def test_it(self):
    assert os.path.exists(self._dest)     # read via self — works fine
```

**JS click for tab buttons that may be scroll-clipped**
`.click()` raises `ElementNotInteractableError` when a tab is partially off-screen.
```python
drv.execute_script("arguments[0].click()", tab_element)
```

**PTY processes need ~2s before saving**
`_TerminalSession._reader()` fills `_buf` at 50ms intervals; the command dispatches
after 500ms. Start the process, sleep 2s, then save — otherwise the buffer is empty.
```python
r = _post('/api/processes/custom',
          command="bash -c 'echo MARKER; sleep 30'",
          host_ip=IP, port='80', protocol='tcp')
time.sleep(2.0)   # let PTY accumulate output before saveProjectAs()
```

**Use `pytest.skip()` for slow async features, not a hard timeout**
If a test depends on nmap completing all port stages (which can take minutes on an
unreachable IP), poll in the fixture with a generous timeout and skip conditionally:
```python
# In fixture:
deadline = time.time() + 90
notes = ''
while time.time() < deadline:
    notes = _get_note(hid)
    if 'expected text' in notes: break
    time.sleep(1.0)
type(self)._notes = notes

# In test:
def test_async_feature(self):
    if 'expected text' not in self._notes:
        pytest.skip("Stage did not complete in time on this target — expected.")
    assert 'expected text' in self._notes
```

---

## Output

Write the complete test file.  Include:
1. Module docstring listing every version tag and what each test proves
2. `PORT`, `IP`, `SEED` constants at top
3. `_free_port` helper
4. `srv` and `drv` module-scoped fixtures with the watchdog disable
5. Helper functions (`js`, `W`, `_select_host`, `_ensure_bottom_processes_tab`, etc.)
6. One pytest class per logical feature group
7. Every assertion must check the ACTUAL DOM state or computed style — never just
   "no exception was raised"
8. Add the port to `run_tests.sh` (show the two lines to add)
