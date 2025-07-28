#!/usr/bin/env python3
"""
Debug script to trace stage response generation for ask_security_medium
"""

import json
import sys
from pathlib import Path

# Load the scenario data directly
scenario_file = Path(__file__).parent / "app" / "data" / "scenarios" / "deposit_account_scenario.json"
with open(scenario_file, 'r', encoding='utf-8') as f:
    scenario_data = json.load(f)

# Get ask_security_medium stage
stage_info = scenario_data["stages"]["ask_security_medium"]

print("=== ask_security_medium Stage Info ===")
print(f"ID: {stage_info.get('id')}")
print(f"Response type: {stage_info.get('response_type')}")
print(f"Prompt: {stage_info.get('prompt')}")
print(f"Choices: {stage_info.get('choices')}")
print(f"Input type: {stage_info.get('input_type')}")
print(f"Expected info key: {stage_info.get('expected_info_key')}")
print(f"Skippable: {stage_info.get('skippable')}")

print("\n=== Individual Choices ===")
choices = stage_info.get('choices', [])
for i, choice in enumerate(choices):
    print(f"Choice {i}: {choice}")
    print(f"  - Type: {type(choice)}")
    print(f"  - Value: {choice.get('value', 'NO VALUE')}")
    print(f"  - Label: {choice.get('label', 'NO LABEL')}")

print("\n=== Simulated Backend Response ===")
# Simulate the exact backend generate_stage_response logic
response_type = stage_info.get("response_type", "narrative")
prompt = stage_info.get("prompt", "")

response_data = {
    "stage_id": stage_info.get("id"),
    "response_type": response_type,
    "prompt": prompt,
    "skippable": stage_info.get("skippable", False)
}

# This is the key logic from line 1366-1367
if response_type in ["bullet", "boolean"]:
    response_data["choices"] = stage_info.get("choices", [])
    print(f"Added choices to response_data: {response_data['choices']}")
    
    # choice_groups가 있는 경우 추가
    if stage_info.get("choice_groups"):
        response_data["choice_groups"] = stage_info.get("choice_groups", [])

print(f"\nFinal response_data:")
print(json.dumps(response_data, indent=2, ensure_ascii=False))

print("\n=== WebSocket Data Simulation ===")
# Simulate the WebSocket data transformation from chat_handlers.py lines 54-62
websocket_data = {
    "type": "stage_response",
    "stageId": response_data.get("stage_id"),
    "responseType": response_data.get("response_type"),
    "prompt": response_data.get("prompt"),
    "choices": response_data.get("choices"),
    "skippable": response_data.get("skippable", False),
    "modifiableFields": response_data.get("modifiable_fields")
}

if response_data.get("choice_groups"):
    websocket_data["choiceGroups"] = response_data.get("choice_groups")

print("WebSocket data that would be sent:")
print(json.dumps(websocket_data, indent=2, ensure_ascii=False))

print("\n=== Frontend Data Simulation ===")
# Simulate frontend store data from chatStore.ts lines following stage_response case
frontend_stage_response = {
    'type': 'stage_response',
    'stageId': websocket_data['stageId'],
    'responseType': websocket_data['responseType'],
    'prompt': websocket_data['prompt'],
    'choices': websocket_data['choices'],
    'skippable': websocket_data['skippable'] or False,
    'modifiableFields': websocket_data['modifiableFields']
}

print("Frontend currentStageResponse:")
print(json.dumps(frontend_stage_response, indent=2, ensure_ascii=False))

print(f"\nIs choices array empty? {len(frontend_stage_response.get('choices', [])) == 0}")
print(f"Choices count: {len(frontend_stage_response.get('choices', []))}")