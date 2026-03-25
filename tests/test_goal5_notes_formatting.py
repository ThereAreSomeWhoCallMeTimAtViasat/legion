#!/usr/bin/env python3
"""
Goal 5: Notes ANSI colour formatting must survive:
  A) loadHostDetail re-render (triggered by snapshot every 1.5s while scans run)
  B) Clicking away from Notes tab and clicking back

Tests use separate executeScript calls with real time between them.
Also directly verifies the server round-trip preserves ESC characters.
"""
import os, sys, time, threading, tempfile
import pytest
import urllib.request, json as _json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

PORT = 5090
IP   = '10.99.99.1'
BASE = f'http://127.0.0.1:{PORT}'

_SEED = f"""<?xml version="1.0"?><nmaprun>
  <host><status state="up"/>
    <address addr="{IP}" addrtype="ipv4"/>
    <ports><port protocol="tcp" portid="22">
      <state state="open"/><service name="ssh"/></port></ports>
  </host>
</nmaprun>"""


@pytest.fixture(scope="module")
def srv():
    from app.web.testhelper import create_test_app
    from app.importers.nmap_import import import_nmap_xml
    app, logic, wc = create_test_app()
    app.config['TESTING'] = False
    with tempfile.NamedTemporaryFile(suffix='.xml', mode='w', delete=False) as f:
        f.write(_SEED); p = f.name
    import_nmap_xml(project=logic.activeProject, xml_path=p, output='')
    os.unlink(p)
    t = threading.Thread(target=app.run,
        kwargs={'host': '127.0.0.1', 'port': PORT,
                'use_reloader': False, 'threaded': True}, daemon=True)
    t.start(); time.sleep(2)
    yield {'app': app, 'logic': logic, 'wc': wc, 'url': BASE}


@pytest.fixture(scope="module")
def drv(srv):
    import os as _os
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service
    _os.environ.pop('XAUTHORITY', None); _os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions(); opts.add_argument('--headless')
    d = webdriver.Firefox(service=Service('/usr/bin/geckodriver'), options=opts)
    d.set_window_size(1600, 900); d.implicitly_wait(0)
    d.get(BASE); time.sleep(2)
    yield d
    d.quit()


def js(d, s, *a): return d.execute_script(s, *a)
def W(d, t=10):   return WebDriverWait(d, t)


def api_post(path, payload):
    req = urllib.request.Request(
        f'{BASE}{path}',
        data=_json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    return _json.loads(urllib.request.urlopen(req).read())


def api_get(path):
    return _json.loads(urllib.request.urlopen(f'{BASE}{path}').read())


def get_host_id(drv):
    return js(drv, f"""
        var r = document.querySelector('#hosts-body tr[data-host-ip="{IP}"]');
        return r ? parseInt(r.dataset.hostId) : null;
    """)


# ─── Sub-test A: server round-trip preserves ANSI codes ───────────────────────

def test_a_server_roundtrip_preserves_ansi(drv, srv):
    """
    Directly save a note with ESC codes via the API, fetch it back, verify
    the ESC characters survived storage and retrieval.
    This tests the Python/SQLite layer independently of the JS layer.
    """
    # Select the host first so the host exists with a known ID
    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(0.8)

    host_id = get_host_id(drv)
    assert host_id, "Could not get host_id from DOM"

    # The ANSI note to save: ESC char + colour code + text + reset
    ansi_note = '\x1b[32mGREEN_SERVER\x1b[0m plain'

    # Save via API (same path Ctrl+B uses)
    api_post(f'/api/workspace/hosts/{host_id}/note', {'note': ansi_note})
    time.sleep(0.2)  # brief settle for DB commit

    # Fetch back via the same endpoint loadHostDetail uses
    data = api_get(f'/api/workspace/hosts/{host_id}')
    returned_note = data.get('note', '')

    # ESC char is U+001B — must survive the round-trip
    assert '\x1b' in returned_note, \
        (f"GOAL 5 SUB-TEST A FAILED: ESC character stripped by server.\n"
         f"  Saved:    {repr(ansi_note)}\n"
         f"  Returned: {repr(returned_note)}")

    assert 'GREEN_SERVER' in returned_note, \
        f"Note text lost entirely: {repr(returned_note)}"

    print(f"\nSub-test A PASS: server round-trip preserved ANSI.\n"
          f"  Returned: {repr(returned_note[:60])}")


# ─── Sub-test B: loadHostDetail re-render preserves colour ────────────────────

def test_b_load_host_detail_rerenders_with_colour(drv, srv):
    """
    After saving ANSI note, trigger loadHostDetail (host click = same as
    snapshot-triggered reload), verify notes-display has ansi-fg-green span.
    """
    host_id = get_host_id(drv)
    ansi_note = '\x1b[32mGREEN_RELOAD\x1b[0m text'
    api_post(f'/api/workspace/hosts/{host_id}/note', {'note': ansi_note})
    time.sleep(0.3)

    # CALL A: click another host if there is one, or click body to force
    # a host re-select — simulates the loadHostDetail that snapshot triggers.
    # We click the SAME host row (triggers loadHostDetail which fetches from DB).
    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(1.5)  # allow loadHostDetail to complete

    # Click the Notes tab
    notes_btn = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, '#right-tab-bar [data-tab="notes-right"]')))
    js(drv, 'arguments[0].click()', notes_btn)
    time.sleep(0.3)

    # CALL B: separate executeScript — check notes-display HTML
    html = js(drv, "return document.getElementById('notes-display').innerHTML") or ''

    assert 'GREEN_RELOAD' in html, \
        f"Note text missing after loadHostDetail: {html[:300]}"
    assert 'ansi-fg-green' in html, \
        (f"GOAL 5 SUB-TEST B FAILED: colour lost after loadHostDetail re-render.\n"
         f"  Expected ansi-fg-green span in: {html[:300]}")

    print(f"\nSub-test B PASS: loadHostDetail re-render preserved colour.")


# ─── Sub-test C: snapshot-triggered re-render (real timer) ────────────────────

def test_c_snapshot_triggered_rerender_preserves_colour(drv, srv):
    """
    Save ANSI note, wait 5s (real snapshot cycles fire and call loadHostDetail),
    verify colour still in notes-display. Two separate executeScript calls.
    """
    host_id = get_host_id(drv)
    ansi_note = '\x1b[31mRED_SNAPSHOT\x1b[0m persistent'
    api_post(f'/api/workspace/hosts/{host_id}/note', {'note': ansi_note})
    time.sleep(0.3)

    # CALL A: click host → sets L.selectedHostId, triggers loadHostDetail
    host_row = W(drv).until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]')))
    js(drv, 'arguments[0].click()', host_row)
    time.sleep(1.0)

    # Open Notes tab
    js(drv, "var b=document.querySelector('#right-tab-bar [data-tab=\"notes-right\"]');"
            "if(b) b.click();")
    time.sleep(0.5)

    html_before = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    assert 'ansi-fg-red' in html_before, \
        f"Colour not present before wait: {html_before[:200]}"

    # WAIT: real snapshot cycles fire — no atomicity, real browser time
    time.sleep(5)

    # CALL B: completely separate call
    html_after = js(drv, "return document.getElementById('notes-display').innerHTML") or ''

    assert 'RED_SNAPSHOT' in html_after, \
        f"Note text lost after snapshot cycles: {html_after[:300]}"
    assert 'ansi-fg-red' in html_after, \
        (f"GOAL 5 SUB-TEST C FAILED: colour lost after real snapshot cycles.\n"
         f"  Before: {html_before[:200]}\n"
         f"  After:  {html_after[:200]}")

    print(f"\nSub-test C PASS: colour survived real snapshot cycles.")


# ─── Sub-test D: click away from Notes tab and back ───────────────────────────

def test_d_notes_tab_click_away_and_back(drv, srv):
    """
    After colour appears in Notes tab, click Info tab (different right-panel tab,
    same host, NO host re-select), click Notes tab back.
    The notes-display innerHTML should persist unchanged (CSS show/hide only).
    """
    host_id = get_host_id(drv)
    ansi_note = '\x1b[33mYELLOW_TABSWITCH\x1b[0m stays'
    api_post(f'/api/workspace/hosts/{host_id}/note', {'note': ansi_note})
    time.sleep(0.3)

    js(drv, 'arguments[0].click()',
       W(drv).until(EC.presence_of_element_located(
           (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]'))))
    time.sleep(1.0)

    # CALL A: open Notes tab, verify colour
    js(drv, "var b=document.querySelector('#right-tab-bar [data-tab=\"notes-right\"]');"
            "if(b) b.click();")
    time.sleep(0.5)
    html_before = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    assert 'ansi-fg-yellow' in html_before, \
        f"Colour not present before tab switch: {html_before[:200]}"

    # Click Info tab (different right-panel tab, same host)
    js(drv, "var b=document.querySelector('#right-tab-bar [data-tab=\"info-right\"]');"
            "if(b) b.click();")
    time.sleep(2)  # snapshot fires, may trigger loadHostDetail

    # Click Notes tab back
    js(drv, "var b=document.querySelector('#right-tab-bar [data-tab=\"notes-right\"]');"
            "if(b) b.click();")
    time.sleep(0.5)

    # CALL B: separate call
    html_after = js(drv, "return document.getElementById('notes-display').innerHTML") or ''

    assert 'YELLOW_TABSWITCH' in html_after, \
        f"Note text lost after tab switch: {html_after[:300]}"
    assert 'ansi-fg-yellow' in html_after, \
        (f"GOAL 5 SUB-TEST D FAILED: colour lost after Notes→Info→Notes tab switch.\n"
         f"  Before: {html_before[:200]}\n"
         f"  After:  {html_after[:200]}")

    print(f"\nSub-test D PASS: colour survived Notes→Info→Notes tab switch.")


# ─── Sub-test E: click notes to edit, blur, verify colour survives ─────────────

def test_e_edit_mode_preserves_ansi_on_blur(drv, srv):
    """
    The original bug: clicking notes-display to edit called
    _showNotesEdit(notesDisp.innerText) — innerText strips HTML tags,
    loading plain text into the textarea.  On blur the plain text was
    saved back to the server, permanently destroying the ANSI codes.

    Fix: use notesTa.value (raw ANSI text) instead of innerText.

    Test:
      1. Save ANSI note via API.
      2. Click host → loadHostDetail renders coloured notes-display.
      3. Click notes-display to enter edit mode  [CALL A]
      4. Check textarea value still has ESC codes.
      5. Blur the textarea (simulate clicking away while editing).
      6. Check notes-display still has coloured span  [CALL B — separate].
    """
    host_id = get_host_id(drv)
    ansi_note = '\x1b[36mCYAN_EDIT\x1b[0m keep'
    api_post(f'/api/workspace/hosts/{host_id}/note', {'note': ansi_note})
    time.sleep(0.3)

    js(drv, 'arguments[0].click()',
       W(drv).until(EC.presence_of_element_located(
           (By.CSS_SELECTOR, f'#hosts-body tr[data-host-ip="{IP}"]'))))
    time.sleep(1.0)

    # Open Notes tab
    js(drv, "var b=document.querySelector('#right-tab-bar [data-tab=\"notes-right\"]');"
            "if(b) b.click();")
    time.sleep(0.4)

    # Verify colour is shown before edit
    html_pre = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    assert 'ansi-fg-cyan' in html_pre, \
        f"Colour not present before click-to-edit: {html_pre[:200]}"

    # CALL A: click notes-display to enter edit mode (triggers the bug or fix)
    js(drv, "document.getElementById('notes-display').click();")
    time.sleep(0.3)

    # Check textarea value — must still contain the ESC char (the fix)
    ta_value = js(drv, "return document.getElementById('notes-text').value") or ''
    assert '\x1b' in ta_value, \
        (f"GOAL 5 SUB-TEST E FAILED: innerText stripped ESC from textarea.\n"
         f"  textarea.value: {repr(ta_value[:100])}")
    assert 'CYAN_EDIT' in ta_value, \
        f"Note text lost from textarea: {repr(ta_value[:100])}"

    # Blur the textarea (user clicks elsewhere after editing)
    js(drv, "document.getElementById('notes-text').blur();")
    time.sleep(1.0)  # allow blur handler and loadHostDetail to run

    # CALL B: separate call — notes-display must still be coloured
    html_post = js(drv, "return document.getElementById('notes-display').innerHTML") or ''
    assert 'CYAN_EDIT' in html_post, \
        f"Note text lost after edit+blur: {html_post[:300]}"
    assert 'ansi-fg-cyan' in html_post, \
        (f"GOAL 5 SUB-TEST E FAILED: colour lost after click-to-edit + blur.\n"
         f"  Pre-edit:  {html_pre[:200]}\n"
         f"  Post-blur: {html_post[:200]}")

    print(f"\nSub-test E PASS: colour survived click-to-edit + blur.")
