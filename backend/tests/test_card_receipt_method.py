"""
Test for card_receipt_method metadata field handling
"""

import asyncio
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.graph.nodes.workers.scenario_logic import process_single_info_collection

async def test_card_receipt_method_metadata():
    """Test that card_receipt_method from metadata is properly handled"""
    
    # Mock stage info for card_selection
    stage_info = {
        "stage_id": "card_selection",
        "response_type": "bullet",
        "fields_to_collect": ["card_selection", "card_receipt_method", "transit_function"],
        "choices": [
            {
                "display": "S-Line 체크카드 (후불교통)",
                "value": "sline_transit",
                "default": True,
                "metadata": {
                    "receipt_method": "즉시발급",
                    "transit_enabled": True
                }
            },
            {
                "display": "신한 Deep Dream 체크카드 (후불교통)",
                "value": "deepdream_transit",
                "metadata": {
                    "receipt_method": "배송",
                    "transit_enabled": True
                }
            }
        ]
    }
    
    # Test case 1: Default selection (그걸로 해줘)
    print("\n=== Test 1: Default selection with metadata ===")
    collected_info = {}
    state = {
        "messages": [],
        "current_product": "deposit_account",
        "current_stage": "card_selection",
        "collected_info": collected_info,
        "current_stage_info": stage_info,
        "scenario_data": {
            "scenario_id": "deposit_account_concurrent",
            "stages": {"card_selection": stage_info}
        }
    }
    
    # Simulate user selecting default
    result = await process_single_info_collection(
        state=state,
        stage_info=stage_info,
        user_input="그걸로 해줘",
        collected_info=collected_info,
        scenario_data=state["scenario_data"]
    )
    
    print(f"Collected info: {collected_info}")
    assert "card_selection" in collected_info, "card_selection should be collected"
    assert collected_info["card_selection"] == "sline_transit", f"Expected 'sline_transit' but got {collected_info['card_selection']}"
    assert "card_receipt_method" in collected_info, "card_receipt_method should be collected from metadata"
    assert collected_info["card_receipt_method"] == "즉시발급", f"Expected '즉시발급' but got {collected_info['card_receipt_method']}"
    assert "transit_function" in collected_info, "transit_function should be collected from metadata"
    assert collected_info["transit_function"] == True, f"Expected True but got {collected_info['transit_function']}"
    print("✅ Test 1 passed - Metadata fields properly collected")
    
    # Test case 2: Specific selection (딥드림)
    print("\n=== Test 2: Specific selection with different metadata ===")
    collected_info = {}
    state["collected_info"] = collected_info
    
    result = await process_single_info_collection(
        state=state,
        stage_info=stage_info,
        user_input="딥드림으로 해줘",
        collected_info=collected_info,
        scenario_data=state["scenario_data"]
    )
    
    print(f"Collected info: {collected_info}")
    assert "card_selection" in collected_info, "card_selection should be collected"
    assert collected_info["card_selection"] == "deepdream_transit", f"Expected 'deepdream_transit' but got {collected_info['card_selection']}"
    assert "card_receipt_method" in collected_info, "card_receipt_method should be collected from metadata"
    assert collected_info["card_receipt_method"] == "배송", f"Expected '배송' but got {collected_info['card_receipt_method']}"
    assert "transit_function" in collected_info, "transit_function should be collected from metadata"
    assert collected_info["transit_function"] == True, f"Expected True but got {collected_info['transit_function']}"
    print("✅ Test 2 passed - Different metadata values properly collected")
    
    print("\n✅ All tests passed!")
    print("\nKey findings:")
    print("1. card_receipt_method is properly extracted from metadata")
    print("2. Metadata fields are not incorrectly validated against card choices")
    print("3. Values persist in collected_info correctly")

if __name__ == "__main__":
    asyncio.run(test_card_receipt_method_metadata())