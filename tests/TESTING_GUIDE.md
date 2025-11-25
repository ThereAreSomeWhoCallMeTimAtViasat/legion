# Legion Testing Guide

## Quick Start: Before You Commit

Run this ONE command to catch regressions:

```bash
python -m unittest tests.integration.test_CoreWorkflows.SmokeTests -v
```

If all tests pass ✅ → Safe to commit  
If any test fails ❌ → Your change broke something critical

---

## What Are These Tests?

**Integration tests** = Test how components work together (like you manually test)  
**Unit tests** = Test individual functions in isolation

**You need integration tests** because:
- Your changes often break other features
- Manual testing every workflow takes too long
- You forget to test edge cases

---

## How To Use This Test Suite

### **Before Every Commit**
```bash
# Run smoke tests (30 seconds)
python -m unittest tests.integration.test_CoreWorkflows.SmokeTests

```

### **After Major Changes**
```bash
# Run all integration tests (2 minutes)
python -m unittest tests.integration.test_CoreWorkflows

# Run ALL tests (5 minutes)
python -m unittest discover -t . -s tests -p "test*.py"
```

### **Before Release**
```bash
# Full test suite
python -m unittest discover -t . -s tests -p "test*.py"

# Check coverage (what code isn't tested)
# TODO: Add coverage tooling
```

---

## When To Write New Tests

### ✅ Write Tests When:
1. **You fix a bug** → Write test that would have caught it
2. **Multiple "fix" commits** → Feature needs tests
3. **Database operations** → Data loss would be bad
4. **Process management** → Zombies/hangs are bad
5. **Users report bugs** → Test prevents recurrence

### ❌ Don't Write Tests When:
1. **Still prototyping** → Code will change completely
2. **UI layout/styling** → Too brittle, changes often
3. **Debug/logging code** → Not user-facing

---

## Test Structure

```python
class MyFeatureTest(unittest.TestCase):
    def setUp(self):
        # Create mocks, temp files
        pass
    
    def test_normalCase_worksCorrectly(self):
        """
        WORKFLOW: What the user does
        BUG PREVENTION: What bug this catches
        """
        # Arrange - set up test data
        # Act - call the function
        # Assert - verify it worked
        pass
```

---

## Common Patterns

### **Pattern 1: Test Database Operations**
```python
def test_saveData_thenLoad_dataMatches(self):
    # Save something
    repo.store(data)
    
    # Load it back
    result = repo.get(id)
    
    # Verify it matches
    self.assertEqual(result, data)
```

### **Pattern 2: Test Process Lifecycle**
```python
def test_startProcess_thenKill_statusUpdates(self):
    # Start process
    pid = start_tool()
    
    # Kill it
    kill_process(pid)
    
    # Verify status changed
    self.assertEqual(get_status(pid), "Killed")
```

### **Pattern 3: Test Error Handling**
```python
def test_invalidInput_raisesError(self):
    with self.assertRaises(ValueError):
        do_something(bad_input)
```

---

## Debugging Failed Tests

### Test Fails After Your Change:
1. **Read the error message** - tells you what broke
2. **Check if API changed** - maybe test needs updating
3. **Check if behavior changed** - maybe you broke something
4. **Run test individually** - `python -m unittest tests.integration.test_CoreWorkflows.ProjectWorkflowTest.test_createProject`

### Test Passes But Feature Broken:
1. **Test isn't testing the right thing** - update test
2. **Test is mocking too much** - reduce mocks
3. **Need integration test** - add end-to-end test

---

## Maintenance

### When Code Changes:
- **API changes** → Update test setup (mocks, parameters)
- **Behavior changes** → Update test assertions
- **New features** → Add new tests

### When Tests Get Slow:
- **Move integration tests** to separate file
- **Use test fixtures** instead of recreating data
- **Run subsets** during development

### When Tests Are Brittle (fail randomly):
- **Too many mocks** → Use real objects where possible
- **Timing issues** → Add proper waits/synchronization
- **Order dependent** → Make tests independent

---

## Next Steps

1. **Run smoke tests now** - see current state
2. **Fix failing tests** - match current API
3. **Add tests for recent bugs** - prevent regression
4. **Run before every commit** - catch issues early

## Questions?

- "Test fails but I didn't touch that code" → Your change broke something
- "How do I test PyQt UI code?" → Integration tests + manual QA
- "Tests take too long" → Run smoke tests only
- "I don't know what to test" → Test what you manually test now
