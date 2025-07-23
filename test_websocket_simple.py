#!/usr/bin/env python3
"""
Simple WebSocket test for phone number update
Focuses on the specific test case: 010-1234-5678 -> 010-1234-2747
"""

import asyncio
import json
import aiohttp
from datetime import datetime

# ANSI color codes for better visibility
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'


async def test_phone_update():
    """Test phone number update through WebSocket"""
    url = "ws://localhost:8000/api/v1/ws-chat"
    
    print(f"{BOLD}WebSocket Phone Number Update Test{RESET}")
    print(f"{BOLD}{'='*50}{RESET}")
    print(f"Target: Update phone from 010-1234-5678 to 010-1234-2747")
    print(f"URL: {url}\n")
    
    session = aiohttp.ClientSession()
    collected_info = {}
    
    try:
        # Connect to WebSocket
        print(f"{BLUE}[CONNECT]{RESET} Connecting to WebSocket...")
        ws = await session.ws_connect(url)
        print(f"{GREEN}[SUCCESS]{RESET} Connected to WebSocket\n")
        
        # Helper function to receive and process messages
        async def receive_until_response_end(description: str):
            nonlocal collected_info
            print(f"{YELLOW}[WAITING]{RESET} {description}")
            
            full_response = ""
            messages = []
            
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        messages.append(data)
                        
                        # Process different message types
                        if data.get("type") == "session_initialized":
                            print(f"{GREEN}[SESSION]{RESET} Initialized with message: {data.get('message', '')[:50]}...")
                            
                        elif data.get("type") == "llm_response_chunk":
                            chunk = data.get("chunk", "")
                            full_response += chunk
                            
                        elif data.get("type") == "llm_response_end":
                            print(f"{GREEN}[RESPONSE]{RESET} {full_response}")
                            break
                            
                        elif data.get("type") == "slot_filling_update":
                            slot_data = data.get("data", {})
                            collected_info = slot_data.get("collected_info", {})
                            print(f"{BLUE}[SLOT UPDATE]{RESET} Collected info updated:")
                            print(f"  Phone: {collected_info.get('phone', 'Not set')}")
                            print(f"  Name: {collected_info.get('name', 'Not set')}")
                            print(f"  Birth: {collected_info.get('birth_date', 'Not set')}")
                            
                        elif data.get("type") == "error":
                            print(f"{RED}[ERROR]{RESET} {data.get('message', '')}")
                            
                except asyncio.TimeoutError:
                    print(f"{YELLOW}[TIMEOUT]{RESET} No more messages received")
                    break
                    
            return messages, full_response
        
        # Wait for initialization
        await receive_until_response_end("Waiting for initialization...")
        print()
        
        # Step 1: Set initial phone number
        print(f"{BOLD}Step 1: Setting initial phone number{RESET}")
        message = {"type": "process_text", "text": "내 전화번호는 010-1234-5678이야"}
        print(f"{BLUE}[SEND]{RESET} {message['text']}")
        await ws.send_json(message)
        
        await receive_until_response_end("Waiting for response...")
        print(f"{GREEN}[CHECK]{RESET} Current phone: {collected_info.get('phone', 'Not set')}\n")
        
        # Step 2: Request phone update
        print(f"{BOLD}Step 2: Requesting phone number update{RESET}")
        message = {"type": "process_text", "text": "오육칠팔이 아니고 이칠사칠이야"}
        print(f"{BLUE}[SEND]{RESET} {message['text']}")
        await ws.send_json(message)
        
        msgs, response = await receive_until_response_end("Waiting for confirmation request...")
        print(f"{GREEN}[CHECK]{RESET} Current phone: {collected_info.get('phone', 'Not set')}")
        
        # Check if confirmation is requested
        if "확인" in response or "맞" in response or "변경" in response:
            print(f"{GREEN}[GOOD]{RESET} System is asking for confirmation\n")
        else:
            print(f"{YELLOW}[WARNING]{RESET} System may not be asking for confirmation\n")
        
        # Step 3: Confirm the update
        print(f"{BOLD}Step 3: Confirming the update{RESET}")
        message = {"type": "process_text", "text": "네"}
        print(f"{BLUE}[SEND]{RESET} {message['text']}")
        await ws.send_json(message)
        
        await receive_until_response_end("Waiting for final response...")
        print()
        
        # Final verification
        print(f"{BOLD}Test Results{RESET}")
        print(f"{BOLD}{'='*50}{RESET}")
        print(f"Initial phone: 010-1234-5678")
        print(f"Expected phone: 010-1234-2747")
        print(f"Actual phone: {collected_info.get('phone', 'Not set')}")
        
        success = collected_info.get('phone') == "010-1234-2747"
        if success:
            print(f"\n{GREEN}{BOLD}✓ TEST PASSED!{RESET} Phone number was updated correctly.")
        else:
            print(f"\n{RED}{BOLD}✗ TEST FAILED!{RESET} Phone number was not updated correctly.")
            print(f"\nCurrent collected_info: {json.dumps(collected_info, ensure_ascii=False, indent=2)}")
        
        return success
        
    except Exception as e:
        print(f"\n{RED}[ERROR]{RESET} Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        await session.close()
        print(f"\n{BLUE}[CLEANUP]{RESET} WebSocket connection closed")


async def main():
    """Main runner"""
    print(f"\n{YELLOW}Note: Make sure the backend server is running on localhost:8000{RESET}\n")
    
    success = await test_phone_update()
    
    print(f"\n{BOLD}Test Summary:{RESET}")
    if success:
        print(f"{GREEN}All tests passed!{RESET}")
    else:
        print(f"{RED}Tests failed. Please check the implementation.{RESET}")


if __name__ == "__main__":
    asyncio.run(main())