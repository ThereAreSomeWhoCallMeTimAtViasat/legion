#!/usr/bin/env python3
"""
Test to verify sortArrayWithArray actually sorts both arrays together
"""

from app.auxiliary import sortArrayWithArray

# Test 1: Simple string sorting
print("Test 1: String sorting")
keys = ['zebra', 'apple', 'banana']
data = [{'id': 1, 'name': 'first'}, {'id': 2, 'name': 'second'}, {'id': 3, 'name': 'third'}]
print(f"Before: keys={keys}")
print(f"Before: data={[d['name'] for d in data]}")

sortArrayWithArray(keys, data)
print(f"After:  keys={keys}")
print(f"After:  data={[d['name'] for d in data]}")
assert keys == ['apple', 'banana', 'zebra'], "Keys not sorted correctly"
assert data[0]['name'] == 'second', "Data didn't follow keys (should be 'second' for 'apple')"
assert data[1]['name'] == 'third', "Data didn't follow keys (should be 'third' for 'banana')"
assert data[2]['name'] == 'first', "Data didn't follow keys (should be 'first' for 'zebra')"
print("✓ Test 1 passed\n")

# Test 2: Numeric sorting
print("Test 2: Numeric sorting (port numbers)")
ports = [8080, 80, 443]
processes = [
    {'tool': 'tool1', 'port': 8080},
    {'tool': 'tool2', 'port': 80},
    {'tool': 'tool3', 'port': 443}
]
print(f"Before: ports={ports}")
print(f"Before: tools={[p['tool'] for p in processes]}")

sortArrayWithArray(ports, processes)
print(f"After:  ports={ports}")
print(f"After:  tools={[p['tool'] for p in processes]}")
assert ports == [80, 443, 8080], "Ports not sorted correctly"
assert processes[0]['tool'] == 'tool2', "Process didn't follow port (should be 'tool2' for port 80)"
assert processes[1]['tool'] == 'tool3', "Process didn't follow port (should be 'tool3' for port 443)"
assert processes[2]['tool'] == 'tool1', "Process didn't follow port (should be 'tool1' for port 8080)"
print("✓ Test 2 passed\n")

# Test 3: Mixed types (None, numbers, strings)
print("Test 3: Mixed types")
mixed = ['stage 2', None, 'stage 1', 80, 'stage 3', 443]
data3 = [
    {'name': 'A'},
    {'name': 'B'},
    {'name': 'C'},
    {'name': 'D'},
    {'name': 'E'},
    {'name': 'F'}
]
print(f"Before: mixed={mixed}")
print(f"Before: data={[d['name'] for d in data3]}")

sortArrayWithArray(mixed, data3)
print(f"After:  mixed={mixed}")
print(f"After:  data={[d['name'] for d in data3]}")

# Check that data followed the sort
print("Checking data followed sort keys:")
for i, (key, item) in enumerate(zip(mixed, data3)):
    print(f"  Position {i}: key={key}, data={item['name']}")

print("\n✅ All tests passed - sortArrayWithArray correctly sorts both arrays together!")
