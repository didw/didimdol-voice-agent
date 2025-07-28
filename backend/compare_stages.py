#!/usr/bin/env python3

import json
from pathlib import Path

# Load both scenarios
orig_path = Path('app/data/scenarios/deposit_account_scenario.json')
v2_path = Path('app/data/scenarios/deposit_account_scenario_v2.json')

with open(orig_path, 'r', encoding='utf-8') as f:
    orig_data = json.load(f)

with open(v2_path, 'r', encoding='utf-8') as f:
    v2_data = json.load(f)

orig_stage = orig_data['stages']['ask_security_medium']
v2_stage = v2_data['stages']['ask_security_medium']

print('=== ORIGINAL ask_security_medium ===')
print(json.dumps(orig_stage, indent=2, ensure_ascii=False))

print('\n=== V2 ask_security_medium ===')
print(json.dumps(v2_stage, indent=2, ensure_ascii=False))

print('\n=== DIFFERENCES ===')
orig_keys = set(orig_stage.keys())
v2_keys = set(v2_stage.keys())

if orig_keys != v2_keys:
    print(f'Key differences: Original has {orig_keys - v2_keys}, V2 has {v2_keys - orig_keys}')
else:
    print('Same keys in both scenarios')

different_found = False
for key in orig_keys & v2_keys:
    if orig_stage[key] != v2_stage[key]:
        print(f'Different {key}:')
        print(f'  Original: {orig_stage[key]}')
        print(f'  V2: {v2_stage[key]}')
        different_found = True

if not different_found:
    print('No key-value differences found')

print('\n=== CHOICES COMPARISON ===')
orig_choices = orig_stage.get('choices', [])
v2_choices = v2_stage.get('choices', [])

print(f'Original choices count: {len(orig_choices)}')
print(f'V2 choices count: {len(v2_choices)}')

print('\nOriginal choices:')
for i, choice in enumerate(orig_choices):
    print(f'  {i}: {choice}')

print('\nV2 choices:')
for i, choice in enumerate(v2_choices):
    print(f'  {i}: {choice}')