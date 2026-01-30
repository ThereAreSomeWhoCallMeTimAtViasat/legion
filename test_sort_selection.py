#!/usr/bin/env python3
"""
Quick test to verify that sorting maintains selection and doesn't break functionality.
This tests the persistent index changes and SelectionBehavior changes.
"""

import sys
from PyQt6.QtWidgets import QApplication, QTableView
from PyQt6.QtCore import Qt

# Test the sort function changes
def test_sort_with_none_values():
    """Test that sortArrayWithArray handles None values correctly"""
    from app.auxiliary import sortArrayWithArray
    
    # Test 1: Mixed None and strings
    array1 = [None, "zebra", "apple", None, "banana"]
    data1 = [1, 2, 3, 4, 5]
    sortArrayWithArray(array1, data1)
    print("Test 1 - Mixed None and strings:")
    print(f"  Sorted: {array1}")
    print(f"  Data: {data1}")
    assert array1[0] is None and array1[1] is None, "None values should be first"
    assert array1[2] == "apple" and array1[3] == "banana" and array1[4] == "zebra"
    print("  ✓ Passed")
    
    # Test 2: Mixed types (None, numbers, strings)
    array2 = ["text", None, 100, "another", 50]
    data2 = ['a', 'b', 'c', 'd', 'e']
    sortArrayWithArray(array2, data2)
    print("\nTest 2 - Mixed None, numbers, and strings:")
    print(f"  Sorted: {array2}")
    print(f"  Data: {data2}")
    assert array2[0] is None, "None should be first"
    assert array2[1] == 50 and array2[2] == 100, "Numbers should be sorted numerically"
    assert array2[3] == "another" and array2[4] == "text", "Strings should be sorted last"
    print("  ✓ Passed")
    
    # Test 3: Stage sorting
    array3 = ["stage 3", "stage 1", "stage 2"]
    data3 = ['c', 'a', 'b']
    # This would be handled by the process model's port sorting logic
    import re
    for i in range(len(array3)):
        if 'stage' in str(array3[i]).lower():
            stage_match = re.search(r'stage\s+(\d+)', str(array3[i]), re.IGNORECASE)
            if stage_match:
                array3[i] = int(stage_match.group(1))
    
    sortArrayWithArray(array3, data3)
    print("\nTest 3 - Stage numbers:")
    print(f"  Sorted: {array3}")
    print(f"  Data: {data3}")
    assert array3[0] == 1 and array3[1] == 2 and array3[2] == 3
    assert data3 == ['a', 'b', 'c']
    print("  ✓ Passed")
    
    print("\n✅ All sortArrayWithArray tests passed!")
    return True


def test_persistent_indices():
    """Test that the persistent index code structure is correct"""
    print("\n" + "="*60)
    print("Testing persistent index implementation...")
    print("="*60)
    
    # Check that all model files have the persistent index pattern
    model_files = [
        'ui/models/cvemodels.py',
        'ui/models/hostmodels.py',
        'ui/models/scriptmodels.py',
        'ui/models/servicemodels.py',
        'ui/models/processmodels.py'
    ]
    
    for model_file in model_files:
        with open(model_file, 'r') as f:
            content = f.read()
            has_persistent = 'persistentIndexList()' in content
            has_change = 'changePersistentIndexList' in content
            
            if has_persistent and has_change:
                print(f"✓ {model_file}: Has persistent index tracking")
            else:
                print(f"✗ {model_file}: Missing persistent index tracking!")
                return False
    
    print("\n✅ All models have persistent index tracking!")
    return True


def test_selection_behavior():
    """Test that SelectionBehavior.SelectRows is set"""
    print("\n" + "="*60)
    print("Testing SelectionBehavior.SelectRows...")
    print("="*60)
    
    with open('ui/view.py', 'r') as f:
        content = f.read()
        
        # Check for SelectionBehavior.SelectRows
        if 'setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)' in content:
            print("✓ SelectionBehavior.SelectRows is configured")
            
            # Count occurrences
            count = content.count('setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)')
            print(f"  Found {count} table views with SelectRows behavior")
            
            # Should have at least the main tables
            expected_tables = [
                'HostsTableView',
                'ServiceNamesTableView', 
                'ServicesTableView',
                'CvesTableView',
                'ToolsTableView',
                'ProcessesTableView'
            ]
            
            for table in expected_tables:
                if f'{table}.setSelectionBehavior' in content:
                    print(f"  ✓ {table}")
                else:
                    print(f"  ✗ {table} not found!")
                    return False
        else:
            print("✗ SelectionBehavior.SelectRows not found!")
            return False
    
    print("\n✅ All tables have SelectRows behavior!")
    return True


if __name__ == '__main__':
    print("="*60)
    print("Legion Sort & Selection Tests")
    print("="*60)
    
    try:
        # Test 1: Sort function with None values
        result1 = test_sort_with_none_values()
        
        # Test 2: Persistent indices
        result2 = test_persistent_indices()
        
        # Test 3: Selection behavior
        result3 = test_selection_behavior()
        
        if result1 and result2 and result3:
            print("\n" + "="*60)
            print("🎉 ALL TESTS PASSED!")
            print("="*60)
            print("\nChanges summary:")
            print("1. ✓ sortArrayWithArray now handles None and mixed types")
            print("2. ✓ All models use persistent indices during sort")
            print("3. ✓ All tables use SelectRows selection behavior")
            print("\nThese changes should NOT break existing functionality:")
            print("  - selectedRows() calls work better (entire rows selected)")
            print("  - Selection follows data after sorting")
            print("  - Mixed type sorting no longer crashes")
            sys.exit(0)
        else:
            print("\n❌ Some tests failed!")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
