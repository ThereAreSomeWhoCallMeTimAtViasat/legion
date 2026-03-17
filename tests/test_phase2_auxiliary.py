#!/usr/bin/env python3
"""
Phase 2 Tests: auxiliary.py Qt-free conditional imports
=========================================================
Run with: sudo python3 tests/test_phase2_auxiliary.py

Tests that auxiliary.py can be imported without PyQt6,
while Flask-needed functions (Filters, checkHydraResults,
getTimestamp, sortArrayWithArray) all work correctly.
"""

import os, sys, traceback, subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PASS = FAIL = SKIP = 0

def test(name, fn):
    global PASS, FAIL, SKIP
    try:
        r = fn()
        if r is None or r is True: PASS += 1; print(f"  \u2713 {name}"); return True
        elif r == 'SKIP': SKIP += 1; print(f"  \u2298 {name} (SKIP)"); return False
        else: FAIL += 1; print(f"  \u2717 {name}: {r}"); return False
    except Exception as e:
        FAIL += 1; print(f"  \u2717 {name}: {e}"); traceback.print_exc(); return False

def ok(v, msg=""): return True if v else f"FAIL: {msg}"


print("\n" + "="*60)
print("Phase 2: auxiliary.py conditional Qt imports")
print("="*60 + "\n")

# A1: Filters class works without Qt
def test_a1_filters():
    """Filters() instantiates and has correct defaults"""
    from app.auxiliary import Filters
    f = Filters()
    return ok(f.tcp and f.udp and f.portopen and not f.portclosed,
              "Filters defaults wrong")
test("A1: Filters() instantiates with correct defaults", test_a1_filters)

# A2: Filters.apply() sets values
def test_a2_filters_apply():
    """Filters.apply() sets all filter values"""
    from app.auxiliary import Filters
    f = Filters()
    f.apply(up=True, down=False, checked=True, portopen=True,
            portfiltered=False, portclosed=False, tcp=True, udp=False)
    return ok(f.up and not f.down and not f.udp, "Filters.apply() failed")
test("A2: Filters.apply() sets values", test_a2_filters_apply)

# A3: checkHydraResults detects credentials
def test_a3_hydra_detect():
    """checkHydraResults correctly parses hydra output"""
    from app.auxiliary import checkHydraResults
    output = "[22][ssh] host: 192.168.1.1   login: root   password: toor"
    found, users, passwords = checkHydraResults(output)
    return ok(found and 'root' in users and 'toor' in passwords,
              f"found={found} users={users} passwords={passwords}")
test("A3: checkHydraResults detects credentials", test_a3_hydra_detect)

# A4: checkHydraResults no false positive
def test_a4_hydra_no_false():
    """checkHydraResults empty on normal output"""
    from app.auxiliary import checkHydraResults
    found, users, passwords = checkHydraResults("[INFO] testing 1234 logins via ssh")
    return ok(not found and len(users) == 0, f"false positive: found={found}")
test("A4: checkHydraResults no false positives", test_a4_hydra_no_false)

# A5: sortArrayWithArray works
def test_a5_sort():
    """sortArrayWithArray sorts correctly"""
    from app.auxiliary import sortArrayWithArray
    keys = ['c', 'a', 'b']
    data = [['c-data'], ['a-data'], ['b-data']]
    sortArrayWithArray(keys, data)
    return ok(data[0] == ['a-data'] and data[1] == ['b-data'],
              f"sort wrong: {data}")
test("A5: sortArrayWithArray sorts correctly", test_a5_sort)

# A6: getTimestamp works
def test_a6_timestamp():
    """getTimestamp() returns non-empty string"""
    from app.timing import getTimestamp
    ts = getTimestamp()
    return ok(ts and len(ts) > 0, f"timestamp: {ts!r}")
test("A6: getTimestamp() works", test_a6_timestamp)

# A7: auxiliary.py importable without PyQt6
def test_a7_qt_free():
    """auxiliary.py can be imported without PyQt6 installed"""
    result = subprocess.run(
        [sys.executable, '-c',
         'import sys\n'
         'import builtins; _real = builtins.__import__\n'
         'def _blocked(name, *a, **k):\n'
         '    if name.startswith("PyQt6"): raise ImportError(f"Qt blocked: {name}")\n'
         '    return _real(name, *a, **k)\n'
         'builtins.__import__ = _blocked\n'
         'from app.auxiliary import Filters, checkHydraResults\n'
         'f = Filters()\n'
         'found, u, p = checkHydraResults("[22][ssh] login: root   password: toor")\n'
         'assert found, "hydra not found"\n'
         'print("OK")'],
        capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=15
    )
    if 'OK' in result.stdout:
        return True
    return f"stderr={result.stderr[-300:]!r}"
test("A7: auxiliary.py importable without Qt", test_a7_qt_free)

# A8: settings.py fully importable without PyQt6 (S11 from Phase 1)
def test_a8_settings_qt_free():
    """settings.py + auxiliary.py both work without PyQt6"""
    result = subprocess.run(
        [sys.executable, '-c',
         'import sys\n'
         'import builtins; _real = builtins.__import__\n'
         'def _blocked(name, *a, **k):\n'
         '    if name.startswith("PyQt6"): raise ImportError(f"Qt blocked: {name}")\n'
         '    return _real(name, *a, **k)\n'
         'builtins.__import__ = _blocked\n'
         'from app.settings import AppSettings, Settings\n'
         's = Settings(AppSettings())\n'
         'assert len(s.portActions) > 100, "portActions empty"\n'
         'assert len(s.hostActions) > 0, "hostActions empty"\n'
         'print("OK")'],
        capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=15
    )
    if 'OK' in result.stdout:
        return True
    return f"stderr={result.stderr[-300:]!r}"
test("A8: settings.py fully importable without Qt", test_a8_settings_qt_free)


print(f"\n{'='*60}")
total = PASS + FAIL + SKIP
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
