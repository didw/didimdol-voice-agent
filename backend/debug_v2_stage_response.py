#!/usr/bin/env python3
"""
Debug script to trace stage response generation for ask_security_medium in v2 scenario
"""

import json
import sys
from pathlib import Path

# Load the v2 scenario data directly
scenario_file = Path(__file__).parent / "app" / "data" / "scenarios" / "deposit_account_scenario_v2.json"
with open(scenario_file, 'r', encoding='utf-8') as f:
    scenario_data = json.load(f)

# Get ask_security_medium stage
stage_info = scenario_data["stages"]["ask_security_medium"]

print("=== ask_security_medium Stage Info (v2) ===")
print(f"ID: {stage_info.get('id')}")
print(f"Response type: {stage_info.get('response_type')}")
print(f"Prompt: {stage_info.get('prompt')}")
print(f"Choices: {stage_info.get('choices')}")
print(f"Input type: {stage_info.get('input_type')}")
print(f"Expected info key: {stage_info.get('expected_info_key')}")
print(f"Skippable: {stage_info.get('skippable')}")

print("\n=== Individual Choices (v2) ===")
choices = stage_info.get('choices', [])
for i, choice in enumerate(choices):
    print(f"Choice {i}: {choice}")
    print(f"  - Type: {type(choice)}")
    print(f"  - Value: {choice.get('value', 'NO VALUE')}")
    print(f"  - Label: {choice.get('label', 'NO LABEL')}")

print("\n=== v2 Scenario Differences ===")
print("v2 scenario stages that lead to ask_security_medium:")

# Find all stages that have ask_security_medium as next_stage_id
for stage_id, stage_data in scenario_data["stages"].items():
    transitions = stage_data.get("transitions", [])
    default_next = stage_data.get("default_next_stage_id")
    
    for transition in transitions:
        if transition.get("next_stage_id") == "ask_security_medium":
            print(f"  {stage_id} -> ask_security_medium (transition: {transition.get('condition_description')})")
    
    if default_next == "ask_security_medium":
        print(f"  {stage_id} -> ask_security_medium (default)")

print("\n=== Simulated v2 Backend Response ===")
# Simulate the exact backend generate_stage_response logic for v2
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

print(f"\nFinal v2 response_data:")
print(json.dumps(response_data, indent=2, ensure_ascii=False))

print(f"\nChoices count in v2: {len(response_data.get('choices', []))}")