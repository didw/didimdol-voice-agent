#!/usr/bin/env python3
"""
WebSocket test script to verify phone number update functionality
Tests the actual WebSocket endpoint with real messages to ensure the fixes work
"""

import asyncio
import json
import logging
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WebSocketTestClient:
    """WebSocket client for testing the chat endpoint"""
    
    def __init__(self, url: str = "ws://localhost:8000/api/v1/ws-chat"):
        self.url = url
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.session_id: Optional[str] = None
        self.messages_received: list = []
        self.collected_info: Dict[str, Any] = {}
        
    async def connect(self):
        """Connect to WebSocket endpoint"""
        logger.info(f"Connecting to WebSocket at {self.url}")
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.url)
        logger.info("WebSocket connected successfully")
        
    async def disconnect(self):
        """Disconnect from WebSocket"""
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()
        logger.info("WebSocket disconnected")
        
    async def send_text(self, text: str):
        """Send a text message through WebSocket"""
        message = {
            "type": "process_text",
            "text": text
        }
        logger.info(f"Sending message: {json.dumps(message, ensure_ascii=False)}")
        await self.ws.send_json(message)
        
    async def receive_messages(self, timeout: float = 5.0):
        """Receive messages until timeout or response ends"""
        messages = []
        start_time = asyncio.get_event_loop().time()
        response_ended = False
        
        while not response_ended and (asyncio.get_event_loop().time() - start_time) < timeout:
            try:
                msg = await asyncio.wait_for(self.ws.receive(), timeout=0.5)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    messages.append(data)
                    self.messages_received.append(data)
                    
                    # Log specific message types
                    if data.get("type") == "session_initialized":
                        self.session_id = data.get("session_id", "unknown")
                        logger.info(f"Session initialized: {self.session_id}")
                        logger.info(f"Initial message: {data.get('message', '')}")
                        
                    elif data.get("type") == "llm_response_chunk":
                        logger.debug(f"Response chunk: {data.get('chunk', '')}")
                        
                    elif data.get("type") == "llm_response_end":
                        response_ended = True
                        logger.info(f"Full response: {data.get('full_text', '')}")
                        
                    elif data.get("type") == "slot_filling_update":
                        slot_data = data.get("data", {})
                        self.collected_info = slot_data.get("collected_info", {})
                        logger.info(f"Slot filling update received:")
                        logger.info(f"  Collected info: {json.dumps(self.collected_info, ensure_ascii=False, indent=2)}")
                        
                    elif data.get("type") == "error":
                        logger.error(f"Error received: {data.get('message', '')}")
                        
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {msg}")
                    break
                    
            except asyncio.TimeoutError:
                continue
                
        return messages
    
    async def wait_for_initialization(self):
        """Wait for session initialization messages"""
        logger.info("Waiting for session initialization...")
        await self.receive_messages(timeout=3.0)
        
    def get_collected_phone(self) -> Optional[str]:
        """Get the current phone number from collected info"""
        return self.collected_info.get("phone")


async def test_phone_number_update():
    """Test the phone number update flow through WebSocket"""
    client = WebSocketTestClient()
    
    try:
        # Connect to WebSocket
        await client.connect()
        
        # Wait for initialization
        await client.wait_for_initialization()
        
        logger.info("\n" + "="*60)
        logger.info("TEST SCENARIO: Phone Number Update")
        logger.info("Initial phone: 010-1234-5678")
        logger.info("Target phone: 010-1234-2747")
        logger.info("="*60 + "\n")
        
        # Step 1: Send initial information to establish context
        logger.info("Step 1: Establishing initial context with phone number")
        await client.send_text("내 전화번호는 010-1234-5678이야")
        await client.receive_messages()
        
        initial_phone = client.get_collected_phone()
        logger.info(f"Initial phone number collected: {initial_phone}")
        
        # Step 2: Request phone number update
        logger.info("\nStep 2: Requesting phone number update")
        await client.send_text("오육칠팔이 아니고 이칠사칠이야")
        await client.receive_messages()
        
        # Check if system asks for confirmation
        phone_after_request = client.get_collected_phone()
        logger.info(f"Phone after update request: {phone_after_request}")
        
        # Step 3: Confirm the update
        logger.info("\nStep 3: Confirming the update")
        await client.send_text("네")
        await client.receive_messages()
        
        # Final verification
        final_phone = client.get_collected_phone()
        logger.info(f"\nFinal phone number: {final_phone}")
        
        # Test results
        logger.info("\n" + "="*60)
        logger.info("TEST RESULTS")
        logger.info("="*60)
        logger.info(f"Initial phone: {initial_phone}")
        logger.info(f"Expected final phone: 010-1234-2747")
        logger.info(f"Actual final phone: {final_phone}")
        
        success = final_phone == "010-1234-2747"
        logger.info(f"Test passed: {success}")
        
        if not success:
            logger.error("Phone number was not updated correctly!")
            
            # Debug information
            logger.info("\nDebug Information:")
            logger.info(f"Total messages received: {len(client.messages_received)}")
            
            # Log all slot filling updates
            slot_updates = [m for m in client.messages_received if m.get("type") == "slot_filling_update"]
            logger.info(f"Slot filling updates received: {len(slot_updates)}")
            for i, update in enumerate(slot_updates):
                logger.info(f"\nSlot update {i+1}:")
                logger.info(json.dumps(update.get("data", {}), ensure_ascii=False, indent=2))
        
        return success
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        return False
        
    finally:
        await client.disconnect()


async def test_multiple_scenarios():
    """Test multiple phone update scenarios"""
    scenarios = [
        {
            "name": "Basic number update",
            "initial": "010-1234-5678",
            "update_message": "오육칠팔이 아니고 이칠사칠이야",
            "expected": "010-1234-2747"
        },
        {
            "name": "Different format update",
            "initial": "010-1234-5678", 
            "update_message": "전화번호 뒷자리를 2747로 바꿔주세요",
            "expected": "010-1234-2747"
        },
        {
            "name": "Full number replacement",
            "initial": "010-1234-5678",
            "update_message": "전화번호를 010-9876-5432로 변경해주세요",
            "expected": "010-9876-5432"
        }
    ]
    
    results = []
    
    for scenario in scenarios:
        logger.info(f"\n{'='*80}")
        logger.info(f"Testing scenario: {scenario['name']}")
        logger.info(f"{'='*80}")
        
        client = WebSocketTestClient()
        
        try:
            await client.connect()
            await client.wait_for_initialization()
            
            # Set initial phone
            await client.send_text(f"내 전화번호는 {scenario['initial']}입니다")
            await client.receive_messages()
            
            # Request update
            await client.send_text(scenario['update_message'])
            await client.receive_messages()
            
            # Confirm
            await client.send_text("네")
            await client.receive_messages()
            
            final_phone = client.get_collected_phone()
            success = final_phone == scenario['expected']
            
            results.append({
                "scenario": scenario['name'],
                "success": success,
                "expected": scenario['expected'],
                "actual": final_phone
            })
            
            logger.info(f"Result: {'PASS' if success else 'FAIL'}")
            logger.info(f"Expected: {scenario['expected']}, Actual: {final_phone}")
            
        except Exception as e:
            logger.error(f"Scenario failed with error: {e}")
            results.append({
                "scenario": scenario['name'],
                "success": False,
                "error": str(e)
            })
            
        finally:
            await client.disconnect()
            await asyncio.sleep(1)  # Brief pause between tests
    
    # Summary
    logger.info(f"\n{'='*80}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*80}")
    
    for result in results:
        status = "PASS" if result.get("success") else "FAIL"
        logger.info(f"{result['scenario']}: {status}")
        if not result.get("success"):
            if "error" in result:
                logger.info(f"  Error: {result['error']}")
            else:
                logger.info(f"  Expected: {result['expected']}, Actual: {result.get('actual', 'N/A')}")
    
    total_pass = sum(1 for r in results if r.get("success"))
    logger.info(f"\nTotal: {total_pass}/{len(results)} passed")


async def main():
    """Main test runner"""
    logger.info("Starting WebSocket Phone Number Update Test")
    logger.info("Make sure the backend server is running on localhost:8000")
    logger.info("")
    
    # Run basic test
    success = await test_phone_number_update()
    
    if success:
        logger.info("\nBasic test passed! Running additional scenarios...")
        await test_multiple_scenarios()
    else:
        logger.error("\nBasic test failed. Please fix the issue before running additional tests.")
    
    logger.info("\nTest completed.")


if __name__ == "__main__":
    asyncio.run(main())