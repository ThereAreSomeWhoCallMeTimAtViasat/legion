# UI Regression Checklist

**Purpose:** Quick manual check before committing UI changes to catch regressions.  
**Time:** ~3-5 minutes  
**When to use:** Before committing changes that touch UI, controllers, or repositories

---

## 🔴 CRITICAL - Must Work (2 minutes)

### Data Integrity
- [ ] **Host switching preserves data**
  - Select Host A → add note → select Host B → select Host A again
  - ✅ Pass: Host A's note still there
  - ❌ Fail: Note lost or shows Host B's note

- [ ] **CVE tab switches with host**
  - Select Host A (has CVEs) → click CVE tab → note CVEs shown
  - Select Host B (different CVEs) → CVE tab should update automatically
  - ✅ Pass: CVE tab shows Host B's CVEs
  - ❌ Fail: Still shows Host A's CVEs or empty

- [ ] **Scripts tab clears between hosts**
  - Select Host A (has scripts) → click Scripts tab → note scripts shown
  - Select Host B (different/no scripts) → Scripts tab should update
  - ✅ Pass: Shows Host B's scripts (or empty if none)
  - ❌ Fail: Still shows Host A's scripts

- [ ] **Tool output persists**
  - Run nmap scan → wait for completion → close project
  - Reopen project → click on nmap tool tab
  - ✅ Pass: Scan output still visible with colors
  - ❌ Fail: Output lost or plaintext

- [ ] **Notes save to correct host**
  - Select Host A → add note "Test A" in Notes tab
  - Select Host B → add note "Test B" in Notes tab
  - Select Host A again → check Notes tab
  - ✅ Pass: Shows "Test A" (not "Test B")
  - ❌ Fail: Shows wrong note or empty

---

## 🟡 HIGH PRIORITY - Should Work (2 minutes)

### Visual Feedback
- [ ] **Ctrl+B copies to notes**
  - Select text in any tool output → press Ctrl+B
  - Check Notes tab
  - ✅ Pass: Selected text appears in Notes with formatting
  - ❌ Fail: Nothing copied or plaintext

- [ ] **Tab highlighting**
  - CVE tab turns orange when new CVE data arrives (if implemented)
  - ✅ Pass: Tab changes color
  - ❌ Fail: Tab stays normal color
  - ⚠️ Skip: If not implemented yet

- [ ] **Tool output shows colors**
  - Run any tool (nmap, nikto, etc.)
  - Look at output in tool tab
  - ✅ Pass: Output has syntax highlighting/colors
  - ❌ Fail: Output is plaintext only

### Project Operations
- [ ] **Project save/load works**
  - Add hosts → run scans → add notes → save project
  - Close Legion → reopen Legion → load project
  - ✅ Pass: All data (hosts, scans, notes) restored
  - ❌ Fail: Data missing or corrupted

- [ ] **Multiple tool tabs work**
  - Run 3+ different tools on same host
  - Check each tool tab
  - ✅ Pass: Each tab shows correct tool output independently
  - ❌ Fail: Tabs show wrong output or interfere

---

## 🟢 MEDIUM PRIORITY - Nice to Have (1 minute)

### Process Management
- [ ] **Kill process works**
  - Start long-running scan → right-click in Processes tab → Kill
  - ✅ Pass: Process stops, status updates to "Killed"
  - ❌ Fail: Process keeps running or crashes

- [ ] **Clear process works**
  - Right-click finished process → Clear
  - ✅ Pass: Process removed from Processes tab
  - ❌ Fail: Process still visible or error

### Settings
- [ ] **Settings dialog opens**
  - Open Settings (F2 or menu)
  - ✅ Pass: Dialog opens without errors
  - ❌ Fail: Crash or error message

- [ ] **Config changes persist**
  - Change a setting → Save → Close Legion → Reopen Legion → Check Settings
  - ✅ Pass: Setting saved
  - ❌ Fail: Reverted to default

---

## 🔵 LOW PRIORITY - Polish (1 minute if time)

### Visual Polish
- [ ] **Splitter positions remember** (known broken - expect fail)
  - Adjust splitters → close app → reopen
  - ✅ Pass: Splitters in same position
  - ❌ Fail: Reset to default

- [ ] **Window geometry saves**
  - Resize window → close app → reopen
  - ✅ Pass: Window same size/position
  - ❌ Fail: Reset to default

- [ ] **Tab reordering works**
  - Drag tool tabs to reorder
  - ✅ Pass: Tabs move
  - ❌ Fail: Tabs don't move or crash

---

## 📊 Results

**Date:** _____________  
**Branch:** _____________  
**Commit:** _____________  

**Summary:**
- Critical: ___/5 passing
- High: ___/5 passing
- Medium: ___/4 passing
- Low: ___/3 passing

**Total:** ___/17 checks passing

**Regressions Found:**
1. ___________________________________________
2. ___________________________________________
3. ___________________________________________

**Action:**
- [ ] All critical tests pass → Safe to commit
- [ ] Regressions found → Fix before commit
- [ ] Regressions in low priority → Note in commit message, fix later

---

## Tips for Using This Checklist

1. **Before committing**: Run through Critical section (2 mins)
2. **Before pushing**: Run through Critical + High (4 mins)
3. **Before release**: Run through all sections (5 mins)
4. **Found regression**: Add it to this list for future checks
5. **After fixing bug**: Verify fix + run checklist to ensure no new breaks

## When Tests Fail

If you find a regression:
1. **Document it**: Note which check failed and symptoms
2. **Fix it**: Before committing your changes
3. **Add automated test**: Create integration test to catch it next time
4. **Update checklist**: If it's a new scenario, add to this list

## Integration with Automated Tests

This checklist covers **UI interactions** that automated tests miss.

**Automated tests cover** (run with `python -m unittest discover`):
- ✅ Database operations
- ✅ Data integrity
- ✅ Repository logic
- ✅ Configuration parsing

**This checklist covers** (manual testing required):
- 🎨 Visual updates (tabs, colors, highlighting)
- 🖱️ User interactions (clicking, selecting, dragging)
- 📺 Display rendering (colors, formatting, layout)
- 🔄 Workflow integration (multi-step operations)

**Best practice:** Run automated tests first (1 min), then this checklist (3-5 mins)
