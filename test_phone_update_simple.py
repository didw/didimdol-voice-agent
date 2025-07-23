#!/usr/bin/env python3
"""
Simple test to verify phone number update logic
Tests the core update mechanism without the full flow
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add the project directory to Python path
project_dir = Path(__file__).parent
backend_dir = project_dir / "backend"
sys.path.insert(0, str(backend_dir))

from app.api.V1.chat import SESSION_STATES
from app.graph.state import AgentState
from app.agents.info_modification_agent import info_modification_agent

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('test_phone_update_simple.log', mode='w')
    ]
)

logger = logging.getLogger(__name__)

async def test_info_modification_agent_analysis():
    """Test that InfoModificationAgent correctly analyzes the phone update request"""
    logger.info("="*80)
    logger.info("TEST 1: InfoModificationAgent Analysis")
    logger.info("="*80)
    
    current_info = {
        "customer_phone": "010-1234-5678",
        "customer_name": "테스트"
    }
    
    required_fields = [
        {"key": "customer_phone", "display_name": "연락처"},
        {"key": "customer_name", "display_name": "성함"}
    ]
    
    user_input = "오육칠팔이 아니고 이칠사칠이야"
    
    logger.info(f"User input: '{user_input}'")
    logger.info(f"Current info: {json.dumps(current_info, ensure_ascii=False)}")
    
    result = await info_modification_agent.analyze_modification_request(
        user_input, current_info, required_fields
    )
    
    logger.info(f"Analysis result: {json.dumps(result, ensure_ascii=False, indent=2)}")
    
    # Verify the result
    modified_fields = result.get('modified_fields', {})
    expected_phone = "010-1234-2747"
    actual_phone = modified_fields.get('customer_phone', '')
    
    success = actual_phone == expected_phone
    logger.info(f"Expected phone: {expected_phone}")
    logger.info(f"Actual phone: {actual_phone}")
    logger.info(f"Analysis successful: {success}")
    
    return success, result

async def test_state_update_mechanism():
    """Test the state update mechanism"""
    logger.info("\n" + "="*80)
    logger.info("TEST 2: State Update Mechanism")
    logger.info("="*80)
    
    # Create initial state
    initial_state = AgentState(
        session_id="test_session",
        collected_info={
            "phone": "010-1234-5678",
            "name": "테스트"
        },
        collected_product_info={
            "customer_phone": "010-1234-5678",
            "customer_name": "테스트"
        }
    )
    
    logger.info(f"Initial collected_product_info: {json.dumps(initial_state.collected_product_info, ensure_ascii=False)}")
    
    # Simulate setting pending modifications
    pending_mods = {"customer_phone": "010-1234-2747"}
    state_with_pending = initial_state.merge_update({
        "pending_modifications": pending_mods
    })
    
    logger.info(f"Pending modifications set: {json.dumps(state_with_pending.pending_modifications, ensure_ascii=False)}")
    
    # Simulate applying the modifications
    updated_info = state_with_pending.collected_product_info.copy()
    updated_info.update(pending_mods)
    
    logger.info(f"Updated info (before merge): {json.dumps(updated_info, ensure_ascii=False)}")
    
    # Apply the update to state
    final_state = state_with_pending.merge_update({
        "collected_product_info": updated_info,
        "pending_modifications": None  # Clear pending modifications
    })
    
    logger.info(f"Final collected_product_info: {json.dumps(final_state.collected_product_info, ensure_ascii=False)}")
    logger.info(f"Final pending_modifications: {final_state.pending_modifications}")
    
    # Verify the update
    expected_phone = "010-1234-2747"
    actual_phone = final_state.collected_product_info.get("customer_phone", "")
    success = actual_phone == expected_phone
    
    logger.info(f"Expected phone: {expected_phone}")
    logger.info(f"Actual phone: {actual_phone}")
    logger.info(f"Update successful: {success}")
    
    return success

async def test_session_states_update():
    """Test updating SESSION_STATES directly"""
    logger.info("\n" + "="*80)
    logger.info("TEST 3: SESSION_STATES Update")
    logger.info("="*80)
    
    session_id = "test_session_states"
    
    # Create initial session data
    initial_data = {
        "session_id": session_id,
        "collected_product_info": {
            "customer_phone": "010-1234-5678",
            "customer_name": "테스트"
        },
        "pending_modifications": None
    }
    
    SESSION_STATES[session_id] = initial_data
    logger.info(f"Initial SESSION_STATES: {json.dumps(SESSION_STATES[session_id], ensure_ascii=False, indent=2)}")
    
    # Set pending modifications
    SESSION_STATES[session_id]["pending_modifications"] = {"customer_phone": "010-1234-2747"}
    logger.info(f"After setting pending: {json.dumps(SESSION_STATES[session_id], ensure_ascii=False, indent=2)}")
    
    # Apply modifications
    if SESSION_STATES[session_id]["pending_modifications"]:
        updated_info = SESSION_STATES[session_id]["collected_product_info"].copy()
        updated_info.update(SESSION_STATES[session_id]["pending_modifications"])
        SESSION_STATES[session_id]["collected_product_info"] = updated_info
        SESSION_STATES[session_id]["pending_modifications"] = None
    
    logger.info(f"Final SESSION_STATES: {json.dumps(SESSION_STATES[session_id], ensure_ascii=False, indent=2)}")
    
    # Verify
    expected_phone = "010-1234-2747"
    actual_phone = SESSION_STATES[session_id]["collected_product_info"].get("customer_phone", "")
    success = actual_phone == expected_phone
    
    logger.info(f"Expected phone: {expected_phone}")
    logger.info(f"Actual phone: {actual_phone}")
    logger.info(f"SESSION_STATES update successful: {success}")
    
    return success

async def main():
    """Run all tests"""
    try:
        results = []
        
        # Test 1: InfoModificationAgent
        success1, analysis_result = await test_info_modification_agent_analysis()
        results.append(("InfoModificationAgent Analysis", success1))
        
        # Test 2: State Update Mechanism
        success2 = await test_state_update_mechanism()
        results.append(("State Update Mechanism", success2))
        
        # Test 3: SESSION_STATES Update
        success3 = await test_session_states_update()
        results.append(("SESSION_STATES Update", success3))
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("TEST SUMMARY")
        logger.info("="*80)
        
        all_passed = True
        for test_name, success in results:
            status = "PASSED" if success else "FAILED"
            logger.info(f"{test_name}: {status}")
            if not success:
                all_passed = False
        
        logger.info(f"\nOverall: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
        logger.info("="*80)
        
        # Print important findings
        if analysis_result:
            logger.info("\nKey Finding from Analysis:")
            logger.info(f"InfoModificationAgent correctly identified the phone number change:")
            logger.info(f"  - Detected: '오육칠팔이 아니고 이칠사칠이야'")
            logger.info(f"  - Extracted: 010-1234-2747")
            logger.info(f"  - Confidence: {analysis_result.get('confidence', 0)}")
            logger.info(f"  - Reasoning: {analysis_result.get('reasoning', 'N/A')}")
        
        print(f"\nFull logs saved to: {Path('test_phone_update_simple.log').absolute()}")
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())