#!/usr/bin/env python3
"""
Test script to debug phone number update flow
Tests updating phone number from 010-1234-5678 to 010-1234-2747
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
from app.agents.info_modification_agent import InfoModificationAgent
from langchain_core.messages import HumanMessage, AIMessage

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('test_phone_update.log', mode='w')
    ]
)

logger = logging.getLogger(__name__)

class TestWebSocketClient:
    """Mock WebSocket client for testing"""
    def __init__(self, session_id):
        self.session_id = session_id
        self.sent_messages = []
        
    async def send(self, message):
        """Mock send method that logs messages"""
        self.sent_messages.append(message)
        logger.info(f"WebSocket would send: {message}")

async def test_phone_update():
    """Test phone number update flow"""
    logger.info("="*80)
    logger.info("Starting phone number update test")
    logger.info("="*80)
    
    # Create test session
    session_id = "test_session_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Initialize session with phone number - mimicking the AgentState structure
    initial_data = {
        "session_id": session_id,
        "collected_info": {
            "phone": "010-1234-5678",
            "name": "테스트",
            "birth_date": "1990-01-01"
        },
        "collected_product_info": {},
        "messages": [],
        "error": "",
        "next": "orchestrator",
        "request_type": "chat"
    }
    
    # Create session in SESSION_STATES
    SESSION_STATES[session_id] = initial_data.copy()
    logger.info(f"Created session {session_id}")
    logger.info(f"Initial SESSION_STATES[{session_id}]: {json.dumps(SESSION_STATES[session_id], ensure_ascii=False, indent=2)}")
    
    # Create mock WebSocket
    mock_ws = TestWebSocketClient(session_id)
    
    # Test 1: User says they want to update phone number
    logger.info("\n" + "="*60)
    logger.info("TEST 1: User requests phone number update")
    logger.info("="*60)
    
    user_message = "오육칠팔이 아니고 이칠사칠이야"
    logger.info(f"User message: {user_message}")
    
    # Add user message to session
    SESSION_STATES[session_id]["messages"].append(HumanMessage(content=user_message))
    
    # Process with InfoModificationAgent
    agent = InfoModificationAgent()
    
    # Add extra logging to the agent's extract method
    original_extract = agent.extract_modification_info
    def logged_extract(text):
        logger.info(f"InfoModificationAgent.extract_modification_info called with: {text}")
        result = original_extract(text)
        logger.info(f"InfoModificationAgent.extract_modification_info returned: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return result
    agent.extract_modification_info = logged_extract
    
    # Process the message
    response = await agent.process_message(user_message, SESSION_STATES[session_id])
    logger.info(f"Agent response: {json.dumps(response, ensure_ascii=False, indent=2)}")
    
    # Check if pending_modifications was set
    if "pending_modifications" in SESSION_STATES[session_id]:
        logger.info(f"Pending modifications: {json.dumps(SESSION_STATES[session_id]['pending_modifications'], ensure_ascii=False, indent=2)}")
    else:
        logger.warning("No pending_modifications found in session!")
    
    # Log current session state
    logger.info(f"SESSION_STATES after first message: {json.dumps(SESSION_STATES[session_id], ensure_ascii=False, indent=2)}")
    
    # Test 2: User confirms the change
    logger.info("\n" + "="*60)
    logger.info("TEST 2: User confirms the change")
    logger.info("="*60)
    
    confirm_message = "네"
    logger.info(f"User confirms with: {confirm_message}")
    
    # Add confirmation message to session
    SESSION_STATES[session_id]["messages"].append(HumanMessage(content=confirm_message))
    
    # Add logging to merge_update
    original_merge = agent.merge_update
    async def logged_merge(current_info, updates):
        logger.info(f"merge_update called with:")
        logger.info(f"  current_info: {json.dumps(current_info, ensure_ascii=False, indent=2)}")
        logger.info(f"  updates: {json.dumps(updates, ensure_ascii=False, indent=2)}")
        result = await original_merge(current_info, updates)
        logger.info(f"merge_update returned: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return result
    agent.merge_update = logged_merge
    
    # Process confirmation
    response = await agent.process_message(confirm_message, SESSION_STATES[session_id])
    logger.info(f"Agent response to confirmation: {json.dumps(response, ensure_ascii=False, indent=2)}")
    
    # Final check
    logger.info("\n" + "="*60)
    logger.info("FINAL STATE CHECK")
    logger.info("="*60)
    
    final_state = SESSION_STATES.get(session_id, {})
    logger.info(f"Final SESSION_STATES[{session_id}]: {json.dumps(final_state, ensure_ascii=False, indent=2)}")
    
    # Verify the update
    collected_info = final_state.get("collected_info", {})
    current_phone = collected_info.get("phone", "NOT FOUND")
    expected_phone = "010-1234-2747"
    
    logger.info(f"\nVerification:")
    logger.info(f"  Expected phone: {expected_phone}")
    logger.info(f"  Current phone: {current_phone}")
    logger.info(f"  Update successful: {current_phone == expected_phone}")
    
    if current_phone != expected_phone:
        logger.error(f"PHONE UPDATE FAILED! Expected {expected_phone}, got {current_phone}")
        
        # Additional debugging
        logger.info("\nAdditional debugging info:")
        logger.info(f"  Session exists in SESSION_STATES: {session_id in SESSION_STATES}")
        logger.info(f"  collected_info exists: {'collected_info' in final_state}")
        logger.info(f"  phone field exists: {'phone' in collected_info}")
        
        # Check if there are any pending modifications left
        if "pending_modifications" in final_state:
            logger.info(f"  Pending modifications still present: {json.dumps(final_state['pending_modifications'], ensure_ascii=False, indent=2)}")
    else:
        logger.info("PHONE UPDATE SUCCESSFUL!")
    
    # Log all WebSocket messages that would have been sent
    logger.info(f"\nWebSocket messages that would have been sent: {len(mock_ws.sent_messages)}")
    for i, msg in enumerate(mock_ws.sent_messages):
        logger.info(f"  Message {i+1}: {msg}")
    
    return current_phone == expected_phone

async def test_direct_merge_update():
    """Test merge_update function directly"""
    logger.info("\n" + "="*80)
    logger.info("Testing merge_update function directly")
    logger.info("="*80)
    
    agent = InfoModificationAgent()
    
    current_info = {
        "phone": "010-1234-5678",
        "name": "테스트",
        "birth_date": "1990-01-01"
    }
    
    updates = {
        "phone": "010-1234-2747"
    }
    
    logger.info(f"Before merge_update:")
    logger.info(f"  current_info: {json.dumps(current_info, ensure_ascii=False)}")
    logger.info(f"  updates: {json.dumps(updates, ensure_ascii=False)}")
    
    result = await agent.merge_update(current_info, updates)
    
    logger.info(f"After merge_update:")
    logger.info(f"  result: {json.dumps(result, ensure_ascii=False)}")
    logger.info(f"  Phone updated correctly: {result.get('phone') == '010-1234-2747'}")

async def main():
    """Run all tests"""
    try:
        # Test direct merge_update first
        await test_direct_merge_update()
        
        # Then test full flow
        success = await test_phone_update()
        
        logger.info("\n" + "="*80)
        logger.info(f"Test completed. Success: {success}")
        logger.info("="*80)
        
        # Print log file location
        print(f"\nFull logs saved to: {Path('test_phone_update.log').absolute()}")
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())