# Legion Feature Testing Checklist
## Features to Test from Recent Development

Based on commits from **ifly53e** and **therearesomewhocallmetimatviasat** (60+ commits)

**Legend**:
- ✅ **KNOWN WORKING** - Completed, ready to test
- ⚠️ **UNCERTAIN** - From TROUBLESHOOTING.md unchecked items, may not work yet
- 🐛 **TESTING WILL HELP** - Write tests to discover if it works

---

## 🔴 CRITICAL - Data Integrity Features

### 1. HTML Output Storage (commit ee39adf) ✅
**Status**: KNOWN WORKING (completed in TROUBLESHOOTING.md)
**What Changed**: Tool output now saved as HTML instead of plaintext for color formatting
**Files**: `controller/controller.py`, `ui/view.py`, database storage
**Risk**: High - Could lose scan data if broken
**Test Priority**: ⭐⭐⭐⭐⭐

**Why Test**: Already working - tests prevent regression

**Testable Behaviors**:
- [ ] Process output saved as HTML with color codes
- [ ] Reopen project → HTML output restored correctly
- [ ] HTML output displays with correct formatting
- [ ] Database size increase acceptable
- [ ] Old plaintext projects can still be opened

---

### 2. Tool Tab Output Persistence (commit e46ca2c) ✅
**Status**: KNOWN WORKING (completed in TROUBLESHOOTING.md)
**What Changed**: bash/msfconsole tool tab output now saved and restored from database
**Files**: Database repositories, controller
**Risk**: High - Users lose tool output if broken
**Test Priority**: ⭐⭐⭐⭐⭐

**Why Test**: Already working - tests prevent regression

**Testable Behaviors**:
- [ ] bash tool output saved to database
- [ ] msfconsole output saved to database
- [ ] Close project → reopen → output still there
- [ ] Interactive commands saved with original output
- [ ] Multiple tool tabs persist independently

---

### 3. Notes Save Fix (commit 9f41c83)
**What Changed**: Fixed bug where notes were not being saved to the selected host
**Files**: Note repository, UI
**Risk**: High - Users lose notes
**Test Priority**: ⭐⭐⭐⭐⭐

**Testable Behaviors**:
- [ ] Add note to host → saves correctly
- [ ] Switch hosts → notes don't get mixed up
- [ ] Close/reopen project → notes persist
- [ ] Delete host → notes deleted
- [ ] Multiple notes per host work

---

### 4. Configuration Versioning (commit 5ee3040) 🐛
**Status**: TESTING WILL HELP - Core works, some edge cases uncertain
**What Changed**: Can maintain multiple legion.conf versions and switch between them
**Files**: `app/settings.py`, UI dialogs
**Risk**: Medium - Could corrupt config
**Test Priority**: ⭐⭐⭐⭐

**Known Issues from TROUBLESHOOTING.md**:
- [ ] changing the matchsettings in a profile and then saving the profile and the activating the profile does not capture a positive match

**Why Test Anyway**: Basic functionality works, tests will find edge cases
**Recommendation**: Test basic save/load, mark match settings behavior as known issue

**Testable Behaviors**:
- [ ] Save config version → creates backup in /backup folder ✅ (works)
- [ ] Load previous config version → restores correctly ✅ (works)
- [ ] Multiple versions can coexist ✅ (works)
- [ ] Active config switches correctly via F2 dialog ✅ (works)
- [ ] Backup timestamps are correct ✅ (works)
- [ ] Profile matchSettings activate correctly ⚠️ (known bug - expect failure)

---

### 5. Config Syntax Validation (commit c788da3)
**What Changed**: Added legion.conf syntax and error checking when editing in GUI
**Files**: Settings, config dialog
**Risk**: Medium - Could prevent app from starting
**Test Priority**: ⭐⭐⭐⭐

**Testable Behaviors**:
- [ ] Invalid config syntax → error message shown
- [ ] Valid config → saves successfully
- [ ] Config edit dialog validates before save
- [ ] Backup created before save
- [ ] Can recover from bad config

---

## 🟡 HIGH - UI/UX Features

### 6. Tab Switching Data Updates (commits 21d40c2, b1e5cc4)
**What Changed**: 
- Fixed CVE tables not switching with host changes
- Fixed scripts tab not clearing between hosts
**Files**: UI views, table models
**Risk**: Medium - Shows wrong data to user
**Test Priority**: ⭐⭐⭐⭐

**Testable Behaviors**:
- [ ] Select host A → CVEs for host A shown
- [ ] Select host B → CVEs switch to host B
- [ ] Scripts tab clears when switching hosts
- [ ] Scripts tab shows correct scripts for new host
- [ ] No data mixing between hosts

---

### 7. Splitter Position Persistence (commit 1fea753) ⚠️
**Status**: UNCERTAIN - Has open issues in TROUBLESHOOTING.md
**What Changed**: Remember window geometry and splitter positions between sessions
**Files**: `ui/view.py`, settings
**Risk**: Low - UI annoyance only
**Test Priority**: ⭐⭐⭐

**Known Issues from TROUBLESHOOTING.md**:
- [ ] window resize is not being saved
- [ ] splitter_2 for hosts not saving and restoring
- [ ] check different splitter 2 for different tabs

**Why NOT Test Yet**: Still has bugs - tests would fail
**Recommendation**: Fix issues first, then write tests to prevent regression

**Testable Behaviors** (once fixed):
- [ ] Adjust splitters → close app → reopen → positions restored
- [ ] Switch tabs → splitter positions saved per tab
- [ ] Window geometry saved/restored
- [ ] splitter_2 works for hosts tab
- [ ] Each tab has independent splitter positions

---

### 8. Tab Highlighting (commits 9c84ce8, 16e7067, 648cbbe)
**What Changed**: Tabs turn orange when they contain new information
**Files**: `ui/view.py`, tab management
**Risk**: Low - Visual indicator only
**Test Priority**: ⭐⭐

**Testable Behaviors**:
- [ ] New CVE data → CVE tab turns orange
- [ ] New info → Information tab turns orange  
- [ ] View tab → tab returns to normal color
- [ ] Notes tab stays orange when appropriate
- [ ] Orange flash on Ctrl+B press

---

### 9. Tool Tab Reordering (commit eaa8f8c)
**What Changed**: Reorder tool tabs immediately when matches found
**Files**: Tool tab management
**Risk**: Low - UI convenience
**Test Priority**: ⭐⭐

**Testable Behaviors**:
- [ ] Match found → tab moves to correct position
- [ ] Multiple matches → tabs sorted correctly
- [ ] Manual reordering still works
- [ ] Reordering doesn't lose data

---

## 🟢 MEDIUM - Process Management

### 10. Process Context Menu (commit 2afc5a0) 🐛
**Status**: TESTING WILL HELP - Most works, some edge cases uncertain
**What Changed**: Kill/Retry/Clear improvements
**Files**: Controller, process management
**Risk**: Medium - Could leave zombie processes
**Test Priority**: ⭐⭐⭐⭐

**Known Issues from TROUBLESHOOTING.md**:
- [ ] should a right click kill give a process crashed error?
- [ ] make resetDisplayStatusForOpenProcesses behavior (show cleared processes on project reopen) an option

**Why Test Anyway**: Core functionality works, tests document expected behavior
**Recommendation**: Test what works, document uncertain behavior

**Testable Behaviors**:
- [ ] Kill process → actually terminates (no zombie) ✅ (works)
- [ ] Kill process → status updates in database ✅ (works)
- [ ] Retry process → creates new process with same params ✅ (works)
- [ ] Retry process → appends -retryX to tab title ✅ (works)
- [ ] Clear process → removes from UI ✅ (works)
- [ ] Clear process → database updated correctly ✅ (works)
- [ ] Right-click kill error behavior 🐛 (uncertain - test to document)
- [ ] Cleared processes on reopen 🐛 (behavior uncertain - test to document)

---

### 11. Interactive Terminal (commits 0490835, 4c11640, 6614b54) 🐛
**Status**: TESTING WILL HELP - Partially working, some features incomplete
**What Changed**: 
- bash/msfconsole interactive in terminal
- Fixed PTY configuration errors
- Ctrl+B preserve formatting
**Files**: Terminal handling, PTY configuration
**Risk**: Medium - Process interaction
**Test Priority**: ⭐⭐⭐

**Known Issues from TROUBLESHOOTING.md**:
- [ ] right click run does not put msfconsole in a terminal...still qtextedit
- [ ] terminal portactions are not added to tools tab table list
- [ ] add history (up arrow) to interactive

**Why Test Anyway**: Tests will show what works and what doesn't
**Recommendation**: Write tests for working parts, mark failing tests as @expected_failure for broken parts

**Testable Behaviors**:
- [ ] bash commands execute interactively ✅ (works)
- [ ] msfconsole commands execute interactively ✅ (works)
- [ ] No stty ioctl errors ✅ (fixed)
- [ ] Ctrl+B preserves formatting ✅ (works)
- [ ] No double entries on Ctrl+B ✅ (works)
- [ ] Interactive output saved to database ✅ (works)
- [ ] Right-click msfconsole opens terminal ⚠️ (broken - don't test yet)
- [ ] Terminal port actions in tools table ⚠️ (broken - don't test yet)
- [ ] Up arrow history in interactive ⚠️ (not implemented - don't test yet)

---

### 12. Match Filtering (commit 6b1cd1b)
**What Changed**: Prevent substring patterns from giving false positive results
**Files**: Pattern matching, tool scheduling
**Risk**: Medium - Could miss or over-trigger tools
**Test Priority**: ⭐⭐⭐

**Testable Behaviors**:
- [ ] Pattern "ssh" doesn't match "http" 
- [ ] Substring matches filtered correctly
- [ ] Full word matches still work
- [ ] Regex patterns work correctly
- [ ] No false positives in tool triggering

---

## 🔵 LOW - Maintenance/Polish

### 13. Log Directory Management (commit c6be1ba)
**What Changed**: Logs moved to ./log folder, exposed in settings
**Files**: Logging configuration, settings
**Risk**: Low - Logging feature
**Test Priority**: ⭐⭐

**Testable Behaviors**:
- [ ] Logs created in ./log folder
- [ ] Log directory setting works
- [ ] Can view log files from UI
- [ ] Log rotation works
- [ ] Old logs cleaned up

---

### 14. Services Table Port Column (commit d0a0c67)
**What Changed**: Added port column to services table
**Files**: Service table model
**Risk**: Low - Display enhancement
**Test Priority**: ⭐⭐

**Testable Behaviors**:
- [ ] Port column displays correctly
- [ ] Port data matches actual port
- [ ] Sorting by port works
- [ ] Column can be resized

---

### 15. Duplicate Tool Handling (commit 4b31ef1)
**What Changed**: Setting for how to handle duplicate calls on tools and scripts
**Files**: Settings, tool coordinator
**Risk**: Low - User preference
**Test Priority**: ⭐⭐

**Testable Behaviors**:
- [ ] Setting to skip duplicates works
- [ ] Setting to allow duplicates works  
- [ ] Setting to append duplicates works
- [ ] Nmap stages deduplicated properly

---

### 16. Purge Results Function (commit 3875fa9)
**What Changed**: Purge deletes scan/processes/ports/CVEs but keeps info tab and notes
**Files**: Database repositories
**Risk**: Medium - Could delete too much or too little
**Test Priority**: ⭐⭐⭐

**Testable Behaviors**:
- [ ] Purge → scan data deleted
- [ ] Purge → processes deleted
- [ ] Purge → ports deleted
- [ ] Purge → CVEs deleted
- [ ] Purge → Information tab preserved
- [ ] Purge → Notes preserved
- [ ] Host ready for rescan after purge

---

### 17. Database Tool Tab Deletion (commit 8782a7c)
**What Changed**: Fixed incomplete host deletion - now deletes tool tabs
**Files**: Repository delete methods
**Risk**: Medium - Database cleanup
**Test Priority**: ⭐⭐⭐

**Testable Behaviors**:
- [ ] Delete host → all tool tabs deleted
- [ ] Delete host → no orphaned records
- [ ] Delete host → database size decreases
- [ ] Delete scan → all related data deleted

---

### 18. CVE Tab Auto-refresh (commit 2e2e00c)
**What Changed**: CVEs tab automatically refreshes and sorts by CVSS score
**Files**: CVE tab, models
**Risk**: Low - Display feature
**Test Priority**: ⭐⭐

**Testable Behaviors**:
- [ ] New CVE → tab auto-refreshes
- [ ] CVEs sorted by CVSS score (high to low)
- [ ] Manual refresh still works
- [ ] Sorting persists across sessions

---

### 19. Information Tab Visual Feedback (commits f4bf8a2, e8ce529)
**What Changed**: 
- Information tab blinks changed data
- Fixed highlight logic to turn orange correctly
**Files**: Information tab UI
**Risk**: Low - Visual feedback
**Test Priority**: ⭐

**Testable Behaviors**:
- [ ] New information → field blinks/highlights
- [ ] Tab turns orange on new data
- [ ] Viewing tab clears orange
- [ ] Multiple fields can highlight simultaneously

---

### 20. Missing Script Handling (commit 8151989)
**What Changed**: Handle missing scripts (e.g., smbenum.sh) with error messages
**Files**: Script execution
**Risk**: Low - Error handling
**Test Priority**: ⭐⭐

**Testable Behaviors**:
- [ ] Missing script → error message shown
- [ ] Error doesn't crash app
- [ ] Error logged appropriately
- [ ] User knows which script is missing

---

### 21. Ctrl+B Improvements (commits a8984e7, e63c906, c75ce0e)
**What Changed**: 
- Ctrl+B works from tool output
- HTML formatting preserved
- Orange flash on press
- Prevent double entries
**Files**: Key event handling, clipboard
**Risk**: Low - Convenience feature
**Test Priority**: ⭐⭐

**Testable Behaviors**:
- [ ] Ctrl+B copies selection to notes
- [ ] HTML formatting preserved in notes
- [ ] Orange flash visible
- [ ] No duplicate entries
- [ ] Works from all tool tabs

---

## 📊 Summary by Priority

### Must Test (Priority ⭐⭐⭐⭐⭐):
1. HTML Output Storage
2. Tool Tab Output Persistence  
3. Notes Save Fix

### Should Test (Priority ⭐⭐⭐⭐):
4. Configuration Versioning
5. Config Syntax Validation
6. Tab Switching Data Updates
10. Process Context Menu

### Nice to Test (Priority ⭐⭐⭐):
7. Splitter Position Persistence
11. Interactive Terminal
12. Match Filtering
16. Purge Results Function
17. Database Tool Tab Deletion

### Can Skip (Priority ⭐⭐ or ⭐):
8. Tab Highlighting
9. Tool Tab Reordering
13-15, 18-21: Various polish features

---

## Selection Guide

**Choose based on your goals:**

### Goal: Prevent Data Loss
Test: #1, #2, #3, #4, #16, #17

### Goal: Prevent UI Bugs  
Test: #6, #7, #10

### Goal: Prevent Process Issues
Test: #10, #11, #12

### Goal: Maximum Coverage
Test: All Priority ⭐⭐⭐⭐⭐ and ⭐⭐⭐⭐

---

## Testing Strategy Based on Status

### ✅ Test These Now (Known Working - Prevent Regression):
**Features**: 1, 2, 3, 5, 6, 8, 9, 13, 14, 15, 16, 17, 18, 19, 20, 21
**Why**: Already working, tests prevent you from breaking them accidentally
**Test Type**: Standard passing tests

### 🐛 Test These to Discover Behavior (Partially Working):
**Features**: 4, 10, 11, 12
**Why**: Tests will document what works and what doesn't
**Test Type**: Mix of passing tests (working parts) and @expected_failure tests (broken parts)
**Value**: Tests become the documentation of current behavior

### ⚠️ Don't Test These Yet (Known Broken):
**Features**: 7 (Splitter persistence)
**Why**: Known bugs, tests would just fail
**Recommendation**: Fix the bugs first, then write tests

---

## Recommended Testing Approach

### Phase 1: Quick Wins (Test Known Working Features)
**Priority**: Prevent regression on working code
**Test**: Features 1, 2, 3, 5, 6 (All ⭐⭐⭐⭐⭐ or ⭐⭐⭐⭐)
**Time**: ~2 hours to write tests
**Benefit**: Catch 80% of potential regressions

### Phase 2: Document Uncertain Behavior
**Priority**: Use tests to understand what works
**Test**: Features 4, 10, 11 (Mark uncertain parts with @expected_failure)
**Time**: ~1 hour to write tests
**Benefit**: Tests document expected vs actual behavior

### Phase 3: Fix Then Test
**Priority**: Fix known bugs, then prevent regression
**Fix**: Feature 7 (splitter persistence)
**Then Test**: After fixing
**Benefit**: Tests prevent bugs from returning

---

## How to Handle Uncertain Features

When testing features marked 🐛, use this pattern:

```python
def test_feature_workingPart(self):
    """This part works - test normally"""
    # Regular test that should pass
    pass

@unittest.expectedFailure
def test_feature_brokenPart(self):
    """
    Known Issue: Description from TROUBLESHOOTING.md
    This test documents the expected behavior once fixed.
    """
    # Test that will fail until bug is fixed
    pass
```

**Benefits**:
- Tests document what works vs what doesn't
- When you fix a bug, just remove @expectedFailure decorator
- Test suite shows progress (failing → passing)

---

## Next Steps

**Option 1: Maximum Protection (Recommended)**
"Test all ✅ features (1, 2, 3, 5, 6, 8, 9, 13-21)"
→ Comprehensive regression protection

**Option 2: Critical Only**
"Test features 1, 2, 3, 5, 6"
→ Protect data integrity and core UI

**Option 3: Behavior Discovery**
"Test features 4, 10, 11 with @expectedFailure for broken parts"
→ Document what works, what doesn't

**Tell me which option** or select specific features:
- "Option 1" or "Option 2" or "Option 3"
- Or: "Test features 1, 2, 3, 6, and 10"
- Or: "Test all critical features plus process management"

I'll create appropriate tests with:
- Regular passing tests for working features ✅
- @expectedFailure tests for uncertain behavior 🐛
- Skipped tests for known broken features ⚠️
