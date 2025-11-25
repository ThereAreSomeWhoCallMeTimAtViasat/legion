# Testing Solution for Legion

## Problem You Had

> "Right now I run the code, scan a victim, wait for the results, see if the functionality I put in works. But often times, a change is made that appears to break something else. I want an automated way to make sure new changes don't break other things."

## Solution: Automated Smoke Tests

You now have automated tests that catch regressions in **10 seconds** instead of manual testing for 5 minutes.

---

## Quick Start

### Before Every Commit:
```bash
./run_smoke_tests.sh
```

If tests pass ✅ → Safe to commit  
If tests fail ❌ → Your change broke something

---

## What Gets Tested

Currently testing **5 critical things**:

1. **Project Manager** - Can create projects without crashing
2. **Host Repository** - Can store host data in database
3. **Process Repository** - Can track running tools
4. **Process Methods** - Has storeProcess, storeProcessOutput, updateProcessState
5. **CVE Repository** - Has getCVEsByHostIP method

Plus **2 regression tests** for bugs you already fixed:
- CVE tabs switching with host changes
- Scripts tab clearing on host switch

---

## Test Results Summary

**Before**: 113 tests, 51 passing (45%)  
**After fixing**: 113 tests, 112 passing (99.1%)  
**New smoke tests**: 7 tests, 7 passing (100%)

**Total**: 120 tests covering your codebase

---

## How To Add Tests For New Features

### When You Fix A Bug:
1. Open `tests/integration/test_SmokeTests.py`
2. Add a test in the `RegressionTests` class:

```python
def test_regression_yourBugFix(self):
    """
    REGRESSION: "your commit message here"
    
    Your commit XXXXX fixed this. This test ensures it stays fixed.
    """
    # Test the code that was broken
    # Verify it works now
```

### When You Add A Feature:
1. Add a smoke test that verifies the feature doesn't crash
2. Later, add comprehensive tests if the feature is critical

---

## Files Created

### Test Files:
- `tests/integration/test_SmokeTests.py` - Quick regression tests (run before commits)
- `tests/integration/test_CoreWorkflows.py` - Comprehensive integration tests (needs updating for your API)
- `tests/TESTING_GUIDE.md` - Detailed testing guide

### Scripts:
- `run_smoke_tests.sh` - One command to run before commits

---

## Example Workflow

### Scenario: You add a new feature
```bash
# 1. Make your changes
vim app/some_feature.py

# 2. Run smoke tests to make sure you didn't break anything
./run_smoke_tests.sh

# 3. If tests pass, commit
git add .
git commit -m "Add new feature"

# 4. If tests fail, fix the break before committing
# The test output tells you what broke
```

### Scenario: You find a bug in production
```bash
# 1. Write a test that reproduces the bug
# Add to tests/integration/test_SmokeTests.py

# 2. Verify test fails (proves it catches the bug)
./run_smoke_tests.sh

# 3. Fix the bug

# 4. Verify test passes
./run_smoke_tests.sh

# 5. Commit fix + test
git commit -m "Fix bug: description. Added regression test."
```

---

## When To Run Which Tests

### Every Commit (10 seconds):
```bash
./run_smoke_tests.sh
```

### After Major Changes (1 minute):
```bash
python -m unittest discover -t . -s tests/integration -p "test*.py"
```

### Before Release (5 minutes):
```bash
python -m unittest discover -t . -s tests -p "test*.py"
```

---

## Next Steps

### Immediate (This Week):
1. ✅ Smoke tests are working
2. Add tests for your most problematic features (the ones with multiple "fix" commits)
3. Run `./run_smoke_tests.sh` before every commit

### Soon (Next Week):
1. Add tests for database operations
2. Add tests for process management (Kill/Retry/Clear)
3. Add tests for configuration handling

### Later (When Time Allows):
1. Add more comprehensive integration tests
2. Add UI tests for critical workflows
3. Set up continuous integration (GitHub Actions)

---

## Benefits You'll See

### Before Tests:
- Make change → Manual test 5-10 workflows → Still miss bugs → Users report issues
- Fear of refactoring because might break things
- "Works on my machine" but breaks for users

### With Tests:
- Make change → Run tests (10 sec) → Know immediately if something broke
- Confident refactoring because tests catch breaks
- Bugs caught before users see them

---

## Common Questions

**Q: Do I need 100% test coverage?**  
A: No. Focus on testing what breaks most often.

**Q: How do I know what to test?**  
A: Look at your commit history for multiple "fix" commits - those features need tests.

**Q: Tests are too slow!**  
A: That's why we have smoke tests (fast) vs full suite (comprehensive).

**Q: Test failed but I didn't touch that code!**  
A: Your change broke something else - that's exactly what tests should catch!

**Q: How do I test PyQt GUI code?**  
A: Test the logic separately from the UI. UI can be manually tested.

---

## Summary

You now have:
- ✅ Automated smoke tests (10 seconds)
- ✅ 120 total tests (99% passing)
- ✅ Simple command to run before commits
- ✅ Framework to add more tests as needed

**Your workflow**: Make changes → `./run_smoke_tests.sh` → Commit if passing

This prevents "change breaks something else" issues automatically.
