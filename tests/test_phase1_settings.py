#!/usr/bin/env python3
"""
Phase 1 Tests: settings.py Qt-free replacement
===============================================
Run with: sudo python3 tests/test_phase1_settings.py

Tests that settings.py works WITHOUT PyQt6. All 10 tests defined
in the test plan for Phase 1.

These tests run BEFORE the change to establish baseline,
then again AFTER to verify the replacement works identically.
"""

import os, sys, traceback

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
def gt(a, t, msg=""): return True if a > t else f"expected > {t}, got {a} ({msg})"


print("\n" + "="*60)
print("Phase 1: AppSettings reads legion.conf correctly")
print("="*60 + "\n")

# ── S1: Settings loads without Qt ──
def test_s1_import():
    """AppSettings can be imported and instantiated"""
    from app.settings import AppSettings
    s = AppSettings()
    return ok(s is not None)
test("S1: AppSettings instantiates", test_s1_import)

# ── S2: portActions readable and complete ──
def test_s2_port_actions():
    """portActions loaded from [PortActions] section"""
    from app.settings import AppSettings, Settings
    s = Settings(AppSettings())
    return gt(len(s.portActions), 200, "portActions should have 200+ entries")
test("S2: portActions loaded (200+ entries)", test_s2_port_actions)

# ── S3: hostActions readable ──
def test_s3_host_actions():
    """hostActions loaded from [HostActions] section"""
    from app.settings import AppSettings, Settings
    s = Settings(AppSettings())
    return gt(len(s.hostActions), 5, "hostActions should have 5+ entries")
test("S3: hostActions loaded (5+ entries)", test_s3_host_actions)

# ── S4: MatchSettings readable ──
def test_s4_match_settings():
    """MatchSettings loaded correctly with positive/negative lists"""
    from app.settings import AppSettings, Settings
    s = Settings(AppSettings())
    ms = s.matchSettings
    glb = ms.get('global', {})
    pos = glb.get('positive', [])
    neg = glb.get('negative', [])
    r = ok(len(pos) > 0, f"global-positive empty: {pos}")
    if r is not True: return r
    return ok(len(neg) > 0, f"global-negative empty: {neg}")
test("S4: MatchSettings readable (positive + negative)", test_s4_match_settings)

# ── S5: SchedulerSettings (automatedAttacks) ──
def test_s5_scheduler():
    """SchedulerSettings loaded as automatedAttacks list"""
    from app.settings import AppSettings, Settings
    s = Settings(AppSettings())
    return gt(len(s.automatedAttacks), 5, "automatedAttacks should have 5+ tools")
test("S5: SchedulerSettings loaded (automatedAttacks)", test_s5_scheduler)

# ── S6: StagedNmapSettings ──
def test_s6_staged_nmap():
    """StagedNmapSettings stages 1-6 all readable"""
    from app.settings import AppSettings, Settings
    s = Settings(AppSettings())
    for i in range(1, 7):
        attr = f'tools_nmap_stage{i}_ports'
        val = getattr(s, attr, None)
        if not val:
            return f"stage{i} ports empty: {val}"
    return True
test("S6: StagedNmapSettings stages 1-6 loaded", test_s6_staged_nmap)

# ── S7: General settings readable ──
def test_s7_general():
    """GeneralSettings values readable"""
    from app.settings import AppSettings, Settings
    s = Settings(AppSettings())
    return ok(
        hasattr(s, 'general_enable_scheduler') and
        hasattr(s, 'general_max_fast_processes') and
        hasattr(s, 'general_tool_duplication'),
        "general settings missing"
    )
test("S7: GeneralSettings readable", test_s7_general)

# ── S8: fileName() returns the config path ──
def test_s8_filename():
    """AppSettings.actions.fileName() returns the config file path"""
    from app.settings import AppSettings
    s = AppSettings()
    fname = str(s.actions.fileName() or '')
    return ok('legion.conf' in fname, f"fileName={fname!r}")
test("S8: fileName() returns legion.conf path", test_s8_filename)

# ── S9: portTerminalActions readable ──
def test_s9_terminal_actions():
    """portTerminalActions loaded from [PortTerminalActions] section"""
    from app.settings import AppSettings, Settings
    s = Settings(AppSettings())
    return gt(len(s.portTerminalActions), 5, "portTerminalActions should have 5+ entries")
test("S9: portTerminalActions loaded (5+ entries)", test_s9_terminal_actions)

# ── S10: tool-specific match patterns ──
def test_s10_tool_match():
    """Tool-specific match patterns (nikto-positive) loaded"""
    from app.settings import AppSettings, Settings
    s = Settings(AppSettings())
    ms = s.matchSettings
    # Should have at least 'global' and one tool-specific entry
    return gt(len(ms), 1, f"matchSettings has only {len(ms)} entries: {list(ms.keys())}")
test("S10: Tool-specific match patterns (nikto, etc.)", test_s10_tool_match)


print("\n" + "="*60)
print("Phase 1b: Verify no Qt import required at module level")
print("="*60 + "\n")

# ── Simulate importing settings WITHOUT Qt ──
def test_qt_free_import():
    """settings.py uses IniSettingsStore (no PyQt6 at module level)"""
    import subprocess
    # Block PyQt6 entirely and verify settings still loads
    result = subprocess.run(
        [sys.executable, '-c',
         'import sys; '
         # Block PyQt6 so it cannot be imported
         'sys.modules["PyQt6"] = None; '
         'import builtins; _real_import = builtins.__import__\n'
         'def _blocked(name, *a, **k):\n'
         '    if "PyQt6" in name: raise ImportError(f"PyQt6 blocked: {name}")\n'
         '    return _real_import(name, *a, **k)\n'
         'builtins.__import__ = _blocked; '
         'from app.settings import AppSettings; '
         's = AppSettings(); '
         'print("OK" if s else "FAIL")'],
        capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=15
    )
    if 'OK' in result.stdout:
        return True
    return f"stdout={result.stdout!r} stderr={result.stderr[-200:]!r}"
test("S11: settings.py importable without Qt (after fix)", test_qt_free_import)


print(f"\n{'='*60}")
total = PASS + FAIL + SKIP
print(f"Results: {PASS} passed, {FAIL} failed, {SKIP} skipped out of {total}")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
