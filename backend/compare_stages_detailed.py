#!/usr/bin/env python3

import json

with open('app/data/scenarios/deposit_account_scenario_v2.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

ask_security = data['stages']['ask_security_medium']
ask_card = data['stages']['ask_card_receive_method']

print('=== ask_security_medium ===')
for key, value in ask_security.items():
    print(f'{key}: {value}')

print('\n=== ask_card_receive_method ===')
for key, value in ask_card.items():
    print(f'{key}: {value}')

print('\n=== KEY DIFFERENCES ===')
for key in set(ask_security.keys()) | set(ask_card.keys()):
    sec_val = ask_security.get(key, 'MISSING')
    card_val = ask_card.get(key, 'MISSING')
    if sec_val != card_val:
        print(f'{key}:')
        print(f'  security: {sec_val}')
        print(f'  card: {card_val}')