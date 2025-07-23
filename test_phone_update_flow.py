#!/usr/bin/env python3
"""
Test script to debug phone number update flow
Tests updating phone number from 010-1234-5678 to 010-1234-2747
This test simulates the actual flow through personal_info_correction_node
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
from app.graph.nodes.control.personal_info_correction import personal_info_correction_node
from app.graph.state import AgentState
from app.agents.info_modification_agent import info_modification_agent
from langchain_core.messages import HumanMessage, AIMessage

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('test_phone_update_flow.log', mode='w')
    ]
)

logger = logging.getLogger(__name__)

async def test_phone_update_flow():
    """Test phone number update flow through personal_info_correction_node"""
    logger.info("="*80)
    logger.info("Starting phone number update flow test")
    logger.info("="*80)
    
    # Create test session
    session_id = "test_session_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Initialize session state - mimicking the AgentState structure
    initial_state = AgentState(
        session_id=session_id,
        collected_info={
            "phone": "010-1234-5678",
            "name": "테스트",
            "birth_date": "1990-01-01"
        },
        collected_product_info={
            "customer_phone": "010-1234-5678",
            "customer_name": "테스트"
        },
        messages=[],
        error="",
        next="personal_info_correction",
        request_type="chat",
        current_scenario_stage_id="customer_info_check",
        stt_result="",
        pending_modifications=None,
        correction_mode=False
    )
    
    # Create session in SESSION_STATES
    SESSION_STATES[session_id] = initial_state.to_dict()
    logger.info(f"Created session {session_id}")
    logger.info(f"Initial state collected_product_info: {json.dumps(initial_state.collected_product_info, ensure_ascii=False, indent=2)}")
    
    # Test 1: User says they want to update phone number
    logger.info("\n" + "="*60)
    logger.info("TEST 1: User requests phone number update")
    logger.info("="*60)
    
    user_message = "오육칠팔이 아니고 이칠사칠이야"
    logger.info(f"User message: {user_message}")
    
    # Update state with user input
    state_with_input = initial_state.merge_update({
        "stt_result": user_message,
        "messages": initial_state.messages + [HumanMessage(content=user_message)]
    })
    
    # Process through personal_info_correction_node
    result_state = await personal_info_correction_node(state_with_input)
    
    logger.info(f"Response text: {result_state.final_response_text_for_tts}")
    logger.info(f"Pending modifications: {json.dumps(result_state.pending_modifications, ensure_ascii=False, indent=2) if result_state.pending_modifications else 'None'}")
    logger.info(f"collected_product_info after first message: {json.dumps(result_state.collected_product_info, ensure_ascii=False, indent=2)}")
    
    # Update SESSION_STATES
    SESSION_STATES[session_id] = result_state.to_dict()
    
    # Check if pending_modifications was set correctly
    if not result_state.pending_modifications:
        logger.error("No pending_modifications found! Modification request was not processed correctly.")
        return False
    
    # Test 2: User confirms the change
    logger.info("\n" + "="*60)
    logger.info("TEST 2: User confirms the change")
    logger.info("="*60)
    
    confirm_message = "네"
    logger.info(f"User confirms with: {confirm_message}")
    
    # Update state with confirmation
    state_with_confirmation = result_state.merge_update({
        "stt_result": confirm_message,
        "messages": result_state.messages + [HumanMessage(content=confirm_message)]
    })
    
    # Process confirmation through personal_info_correction_node
    final_state = await personal_info_correction_node(state_with_confirmation)
    
    logger.info(f"Response text: {final_state.final_response_text_for_tts}")
    logger.info(f"Pending modifications after confirmation: {json.dumps(final_state.pending_modifications, ensure_ascii=False, indent=2) if final_state.pending_modifications else 'None'}")
    logger.info(f"Final collected_product_info: {json.dumps(final_state.collected_product_info, ensure_ascii=False, indent=2)}")
    
    # Update SESSION_STATES
    SESSION_STATES[session_id] = final_state.to_dict()
    
    # Final verification
    logger.info("\n" + "="*60)
    logger.info("FINAL STATE CHECK")
    logger.info("="*60)
    
    # Check both collected_info and collected_product_info
    current_phone_product = final_state.collected_product_info.get("customer_phone", "NOT FOUND")
    current_phone_info = final_state.collected_info.get("phone", "NOT FOUND")
    expected_phone = "010-1234-2747"
    
    logger.info(f"\nVerification:")
    logger.info(f"  Expected phone: {expected_phone}")
    logger.info(f"  Current phone (collected_product_info): {current_phone_product}")
    logger.info(f"  Current phone (collected_info): {current_phone_info}")
    logger.info(f"  Update successful: {current_phone_product == expected_phone}")
    
    # Check SESSION_STATES
    session_data = SESSION_STATES.get(session_id, {})
    session_phone = session_data.get("collected_product_info", {}).get("customer_phone", "NOT FOUND")
    logger.info(f"  Phone in SESSION_STATES: {session_phone}")
    
    success = current_phone_product == expected_phone
    
    if not success:
        logger.error(f"PHONE UPDATE FAILED! Expected {expected_phone}, got {current_phone_product}")
        
        # Additional debugging
        logger.info("\nAdditional debugging info:")
        logger.info(f"  Session exists in SESSION_STATES: {session_id in SESSION_STATES}")
        logger.info(f"  collected_product_info exists: {'collected_product_info' in final_state.to_dict()}")
        logger.info(f"  customer_phone field exists: {'customer_phone' in final_state.collected_product_info}")
        logger.info(f"  pending_modifications cleared: {final_state.pending_modifications is None}")
        logger.info(f"  current_scenario_stage_id: {final_state.current_scenario_stage_id}")
        logger.info(f"  correction_mode: {final_state.correction_mode}")
    else:
        logger.info("PHONE UPDATE SUCCESSFUL!")
    
    return success

async def test_direct_info_modification_agent():
    """Test InfoModificationAgent directly"""
    logger.info("\n" + "="*80)
    logger.info("Testing InfoModificationAgent directly")
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
    
    logger.info(f"Analyzing: '{user_input}'")
    logger.info(f"Current info: {json.dumps(current_info, ensure_ascii=False)}")
    
    result = await info_modification_agent.analyze_modification_request(
        user_input, current_info, required_fields
    )
    
    logger.info(f"Analysis result: {json.dumps(result, ensure_ascii=False, indent=2)}")
    logger.info(f"Modified fields: {json.dumps(result.get('modified_fields', {}), ensure_ascii=False)}")
    logger.info(f"Expected phone: 010-1234-2747")
    
    modified_phone = result.get('modified_fields', {}).get('customer_phone', '')
    success = modified_phone == "010-1234-2747"
    logger.info(f"Analysis successful: {success}")
    
    return success

async def main():
    """Run all tests"""
    try:
        # Test InfoModificationAgent directly first
        agent_success = await test_direct_info_modification_agent()
        
        # Then test full flow
        flow_success = await test_phone_update_flow()
        
        logger.info("\n" + "="*80)
        logger.info(f"Test results:")
        logger.info(f"  InfoModificationAgent test: {'PASSED' if agent_success else 'FAILED'}")
        logger.info(f"  Full flow test: {'PASSED' if flow_success else 'FAILED'}")
        logger.info(f"  Overall: {'ALL PASSED' if agent_success and flow_success else 'SOME FAILED'}")
        logger.info("="*80)
        
        # Print log file location
        print(f"\nFull logs saved to: {Path('test_phone_update_flow.log').absolute()}")
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())