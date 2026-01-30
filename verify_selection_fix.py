#!/usr/bin/env python3
"""
Quick verification that SelectionBehavior.SelectRows is set in the code.
Run this to confirm the fixes are in place before starting Legion.
"""

import sys

def check_file_contains(filepath, search_strings):
    """Check if file contains all the search strings"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            results = []
            for search_str in search_strings:
                if search_str in content:
                    results.append((search_str, True))
                else:
                    results.append((search_str, False))
            return results
    except FileNotFoundError:
        return [(f"File {filepath} not found", False)]

print("="*70)
print("Verifying Selection Fix Implementation")
print("="*70)

# Check ui/view.py for SelectRows settings
print("\n1. Checking ui/view.py for SelectionBehavior.SelectRows...")
view_checks = [
    "self.ui.ToolsTableView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)",
    "self.ui.ProcessesTableView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)",
    "self.ui.ServicesTableView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)",
    "self.ui.HostsTableView.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)",
]

results = check_file_contains('ui/view.py', view_checks)
all_passed = all(result[1] for result in results)

for search_str, found in results:
    status = "✓" if found else "✗"
    print(f"  {status} {search_str[:60]}...")

# Check app/auxiliary.py for setTableProperties setting
print("\n2. Checking app/auxiliary.py setTableProperties function...")
aux_checks = [
    "def setTableProperties(table, headersLen, hiddenColumnIndexes=[]):",
    "table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)",
]

results2 = check_file_contains('app/auxiliary.py', aux_checks)
all_passed2 = all(result[1] for result in results2)

for search_str, found in results2:
    status = "✓" if found else "✗"
    print(f"  {status} {search_str[:60]}...")

# Check model files for persistent index tracking
print("\n3. Checking model files for persistent index tracking...")
model_files = [
    ('ui/models/processmodels.py', 'persistentIndexList()'),
    ('ui/models/cvemodels.py', 'persistentIndexList()'),
    ('ui/models/hostmodels.py', 'persistentIndexList()'),
    ('ui/models/servicemodels.py', 'persistentIndexList()'),
    ('ui/models/scriptmodels.py', 'persistentIndexList()'),
]

all_passed3 = True
for filepath, search in model_files:
    results3 = check_file_contains(filepath, [search])
    found = results3[0][1]
    all_passed3 = all_passed3 and found
    status = "✓" if found else "✗"
    print(f"  {status} {filepath}: {search}")

# Check sortArrayWithArray fix
print("\n4. Checking app/auxiliary.py for None-safe sorting...")
sort_checks = [
    "def sortArrayWithArray(array, arrayToSort):",
    "def sort_key(x):",
    "if val is None:",
]

results4 = check_file_contains('app/auxiliary.py', sort_checks)
all_passed4 = all(result[1] for result in results4)

for search_str, found in results4:
    status = "✓" if found else "✗"
    print(f"  {status} {search_str}")

# Final summary
print("\n" + "="*70)
if all_passed and all_passed2 and all_passed3 and all_passed4:
    print("✅ ALL FIXES ARE IN PLACE!")
    print("\nTo test:")
    print("  1. Kill any running Legion instances")
    print("  2. Start Legion: python legion.py")
    print("  3. Click on any table cell - entire row should be selected")
    print("  4. Sort any column - selection should follow the data")
    sys.exit(0)
else:
    print("❌ SOME FIXES ARE MISSING!")
    print("\nSome expected changes were not found.")
    print("You may need to re-apply the fixes.")
    sys.exit(1)
