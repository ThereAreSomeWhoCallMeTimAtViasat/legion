#!/bin/bash
# Run this before committing to catch regressions
# Usage: ./run_smoke_tests.sh

echo "======================================"
echo "Running Legion Smoke Tests"
echo "======================================"
echo ""

# Run smoke tests
python -m unittest tests.integration.test_SmokeTests.SmokeTests -v

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ ALL SMOKE TESTS PASSED - Safe to commit!"
else
    echo "❌ SMOKE TESTS FAILED - Fix before committing!"
fi

exit $EXIT_CODE
