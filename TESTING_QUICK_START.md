# Quick Start - UI Regression Testing

Created: November 25, 2025

## 🚀 Use This Today (3 minutes)

Before committing UI changes:

```bash
# 1. Run automated tests (1 min)
python -m unittest discover -t . -s tests/features -p "test*.py"

# 2. Run manual checklist (2 mins - Critical section only)
cat REGRESSION_CHECKLIST.md
# Follow the 5 Critical checks

# 3. Commit if all pass
git commit -m "Your changes"
```

## 📊 Test Status

```bash
# Feature tests (backend/data)
$ python -m unittest discover -t . -s tests/features -p "test*.py"
Ran 49 tests in 0.15s - OK ✅

# UI regression tests (placeholders)
$ python -m unittest tests.integration.test_UIRegressions
Ran 16 tests in 0.07s - OK (skipped=16) ⚠️

# Critical path tests (placeholders)
$ python -m unittest tests.integration.test_CriticalPaths
Ran 5 tests in 0.00s - OK (skipped=5) ⚠️
```

**Total:** 70 tests (49 passing, 21 skipped placeholders)

## 📁 Files

- **`REGRESSION_CHECKLIST.md`** - Use this before committing UI changes ✅
- **`UI_REGRESSION_TESTING_SUMMARY.md`** - Full documentation
- **`tests/integration/test_UIRegressions.py`** - 16 UI test placeholders (implement later)
- **`tests/integration/test_CriticalPaths.py`** - 5 workflow test placeholders (implement later)
- **`tests/features/test_*.py`** - 49 backend tests (all working ✅)

## ⚡ Quick Commands

```bash
# Run all working tests
python -m unittest discover -t . -s tests/features -p "test*.py"

# See UI test placeholders
python -m unittest tests.integration.test_UIRegressions -v

# See workflow test placeholders  
python -m unittest tests.integration.test_CriticalPaths -v

# Open manual checklist
cat REGRESSION_CHECKLIST.md
```

## 🎯 What's Next?

1. **Today:** Start using `REGRESSION_CHECKLIST.md` before commits
2. **This Week:** If you find a UI bug, add it to the checklist
3. **Later:** Implement automated UI tests one at a time (optional)

See `UI_REGRESSION_TESTING_SUMMARY.md` for full details.

---

**The Problem We're Solving:** "When we add new functionality, something else breaks and I notice it when interacting with the program."

**The Solution:** Manual checklist catches UI issues automated tests miss (3 minutes before commit).

**The Future:** Gradually implement automated UI tests so you don't need manual checking.
