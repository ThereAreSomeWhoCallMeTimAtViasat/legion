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
