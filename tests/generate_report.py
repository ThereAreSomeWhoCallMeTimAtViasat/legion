#!/usr/bin/env python3
"""
Generic Legion Selenium Test Report Generator
==============================================
Imported by individual report scripts (generate_report_US03.py etc.).
Provides the shared CSS, screenshot capture, step recording, and HTML render.

Not run directly — each test has its own generate_report_USxx.py that calls
run_scenario() functions then calls render_and_save().
"""

import base64
import os
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Report state (module-level so scenario runners can append freely)
# ---------------------------------------------------------------------------
_report_steps    = []   # [{test, step, annotation, result, png}]
_test_summaries  = []   # [{name, passed}]
_port            = 5085
_base_url        = f'http://127.0.0.1:{_port}'


def configure(port=5085):
    global _port, _base_url
    _port     = port
    _base_url = f'http://127.0.0.1:{port}'


def base_url():
    return _base_url


def make_driver():
    """Headless Firefox, 1600×900."""
    import os as _os
    from selenium import webdriver
    from selenium.webdriver.firefox.service import Service
    _os.environ.pop('XAUTHORITY', None)
    _os.environ.pop('DISPLAY', None)
    opts = webdriver.FirefoxOptions()
    opts.add_argument('--headless')
    svc  = Service('/usr/bin/geckodriver')
    d    = webdriver.Firefox(service=svc, options=opts)
    d.set_window_size(1600, 900)
    d.implicitly_wait(0)
    d.set_script_timeout(30)   # prevent execute_script() hanging indefinitely
    return d


def snap(driver):
    """Return base64 PNG screenshot."""
    return base64.b64encode(driver.get_screenshot_as_png()).decode()


def highlight(driver, selector):
    """Orange outline on selector; returns cleanup lambda."""
    try:
        driver.execute_script(f"""
            var el = document.querySelector('{selector}');
            if (el) {{
                el.dataset._rhl = el.style.outline || '';
                el.style.outline = '3px solid #f90';
            }}
        """)
    except Exception:
        pass

    def cleanup():
        try:
            driver.execute_script(f"""
                var el = document.querySelector('{selector}');
                if (el) {{
                    el.style.outline = el.dataset._rhl || '';
                    delete el.dataset._rhl;
                }}
            """)
        except Exception:
            pass
    return cleanup


def record(driver, test_name, step_num, annotation, result, css_highlight=None):
    """Take screenshot (with optional highlight), record step."""
    cleanup = None
    if css_highlight:
        cleanup = highlight(driver, css_highlight)
        time.sleep(0.25)

    png = snap(driver)
    if cleanup:
        cleanup()

    _report_steps.append({
        'test':       test_name,
        'step':       step_num,
        'annotation': annotation,
        'result':     result,
        'png':        png,
    })
    status = '✓ PASS' if result else '✗ FAIL'
    print(f'    [{status}] Step {step_num}: {annotation[:72]}')
    return result


def finish_test(name, passed):
    _test_summaries.append({'name': name, 'passed': passed})


# ---------------------------------------------------------------------------
# HTML render
# ---------------------------------------------------------------------------
_CSS = """
* { box-sizing:border-box; margin:0; padding:0 }
body { font-family:'Segoe UI',Arial,sans-serif; background:#1a1a2e; color:#e0e0e0 }
header { background:#16213e; padding:24px 40px; border-bottom:2px solid #0f3460 }
header h1 { font-size:22px; color:#e94560; letter-spacing:1px }
header .meta { color:#888; font-size:12px; margin-top:6px; line-height:1.8 }
.summary-bar { display:flex; gap:14px; padding:18px 40px;
    background:#16213e; border-bottom:1px solid #0f3460; flex-wrap:wrap }
.sc { background:#0f3460; border-radius:8px; padding:10px 20px; min-width:140px }
.sc .lbl { font-size:10px; color:#888; text-transform:uppercase; letter-spacing:1px }
.sc .val { font-size:26px; font-weight:700; margin-top:2px }
.pass { color:#4caf50 } .fail { color:#e94560 } .neutral { color:#90caf9 }
.block { margin:22px 40px; border-radius:10px; overflow:hidden;
    border:1px solid #0f3460 }
.bh { padding:13px 18px; font-size:14px; font-weight:600;
    display:flex; align-items:center; gap:10px }
.bh.pass { background:#1b3a1b; border-left:4px solid #4caf50 }
.bh.fail { background:#3a1b1b; border-left:4px solid #e94560 }
.badge { padding:2px 9px; border-radius:20px; font-size:11px; font-weight:700 }
.badge.pass { background:#4caf50; color:#000 }
.badge.fail { background:#e94560; color:#fff }
.step { display:flex; border-top:1px solid #0f3460 }
.sl { min-width:320px; max-width:320px; padding:14px 18px;
    background:#12192b; display:flex; flex-direction:column; gap:6px }
.sn { font-size:10px; color:#888; text-transform:uppercase; letter-spacing:1px }
.sa { font-size:12px; line-height:1.6; color:#cfd8dc }
.sr { font-size:11px; font-weight:700; margin-top:3px }
.sr.pass { color:#4caf50 } .sr.fail { color:#e94560 }
.ss { flex:1; background:#0a0f1e; padding:8px; display:flex;
    align-items:flex-start }
.ss img { width:100%; border-radius:4px; border:1px solid #0f3460 }
footer { text-align:center; padding:18px; color:#555; font-size:11px;
    border-top:1px solid #0f3460; margin-top:36px }
"""


def render_and_save(title, us_id, description, out_dir='testreport'):
    """Render the accumulated steps to a dated HTML file. Returns the path."""
    from collections import OrderedDict

    now_str   = datetime.now().strftime('%Y%m%d_%H%M%S')
    now_label = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    safe_id   = us_id.replace('-', '').replace(' ', '_')
    filename  = f'{safe_id}_{now_str}.html'
    out_path  = os.path.join(PROJECT_ROOT, out_dir, filename)
    os.makedirs(os.path.join(PROJECT_ROOT, out_dir), exist_ok=True)

    total  = len(_test_summaries)
    passed = sum(1 for t in _test_summaries if t['passed'])
    failed = total - passed
    total_steps  = len(_report_steps)
    passed_steps = sum(1 for s in _report_steps if s['result'])

    by_test = OrderedDict()
    for s in _report_steps:
        by_test.setdefault(s['test'], []).append(s)

    blocks = []
    for ts in _test_summaries:
        tname = ts['name']
        tpass = ts['passed']
        steps = by_test.get(tname, [])
        cls   = 'pass' if tpass else 'fail'
        badge = f'<span class="badge {cls}">{"PASS" if tpass else "FAIL"}</span>'

        step_rows = []
        for s in steps:
            r_cls  = 'pass' if s['result'] else 'fail'
            r_text = '✓ Pass' if s['result'] else '✗ Fail'
            img    = (f'<img src="data:image/png;base64,{s["png"]}" '
                      f'alt="step {s["step"]} screenshot"/>')
            step_rows.append(f"""
            <div class="step">
              <div class="sl">
                <div class="sn">Step {s['step']}</div>
                <div class="sa">{s['annotation']}</div>
                <div class="sr {r_cls}">{r_text}</div>
              </div>
              <div class="ss">{img}</div>
            </div>""")

        blocks.append(f"""
        <div class="block">
          <div class="bh {cls}">{badge} {tname}</div>
          {''.join(step_rows)}
        </div>""")

    overall_cls   = 'pass' if failed == 0 else 'fail'
    overall_label = 'ALL PASS' if failed == 0 else 'FAIL'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>Legion Test Report — {us_id}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>Legion UI Test Report — {us_id}: {title}</h1>
  <div class="meta">
    Server: {_base_url} &nbsp;|&nbsp; Generated: {now_label}<br>
    {description}
  </div>
</header>
<div class="summary-bar">
  <div class="sc"><div class="lbl">Tests</div>
    <div class="val neutral">{total}</div></div>
  <div class="sc"><div class="lbl">Passed</div>
    <div class="val pass">{passed}</div></div>
  <div class="sc"><div class="lbl">Failed</div>
    <div class="val {('fail' if failed else 'pass')}">{failed}</div></div>
  <div class="sc"><div class="lbl">Steps</div>
    <div class="val neutral">{total_steps}</div></div>
  <div class="sc"><div class="lbl">Steps Passed</div>
    <div class="val pass">{passed_steps}</div></div>
  <div class="sc"><div class="lbl">Overall</div>
    <div class="val {overall_cls}">{overall_label}</div></div>
</div>
{''.join(blocks)}
<footer>Legion Flask — Automated UI Test Report &nbsp;|&nbsp;
Selenium + Firefox Headless</footer>
</body>
</html>"""

    with open(out_path, 'w') as f:
        f.write(html)

    print(f'\nReport: {out_path}')
    return out_path
