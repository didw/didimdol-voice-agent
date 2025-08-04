"""
Test for ordinal choice mapping (첫번째, 두번째, etc.)
"""

import asyncio
import json
from app.agents.entity_agent import EntityRecognitionAgent

async def test_ordinal_choice_mapping():
    """Test that ordinal expressions are correctly mapped to choice values"""
    
    entity_agent = EntityRecognitionAgent()
    
    # Test case 1: "두번째로 등록" for security_medium
    print("\n=== Test 1: '두번째로 등록' for security_medium ===")
    stage_info = {
        "stage_id": "security_medium_registration",
        "stage_name": "보안매체 등록",
        "prompt": "보안매체를 선택해주세요",
        "fields_to_collect": ["security_medium", "transfer_limit_once", "transfer_limit_daily"],
        "choice_groups": [
            {
                "group_name": "내가 보유한 보안매체",
                "choices": [
                    {"display": "미래테크 19284019384", "value": "futuretech_19284019384", "default": True},
                    {"display": "코마스(RSA) 12930295", "value": "comas_rsa_12930295"}
                ]
            },
            {
                "group_name": "새로 발급 가능한 보안매체",
                "choices": [
                    {"display": "보안카드", "value": "security_card"},
                    {"display": "신한OTP (10,000원)", "value": "shinhan_otp"}
                ]
            }
        ]
    }
    
    result = await entity_agent.analyze_user_intent(
        user_input="두번째로 등록",
        current_stage="security_medium_registration",
        stage_info=stage_info,
        collected_info={}
    )
    
    print(f"Extracted info: {result.get('extracted_info')}")
    # Note: The actual mapping happens in scenario_logic.py, not in entity_agent
    # Entity agent may extract "두번째" but scenario_logic should map it to "comas_rsa_12930295"
    
    # Test case 2: "첫번째"
    print("\n=== Test 2: '첫번째' ===")
    result = await entity_agent.analyze_user_intent(
        user_input="첫번째",
        current_stage="security_medium_registration",
        stage_info=stage_info,
        collected_info={}
    )
    print(f"Extracted info: {result.get('extracted_info')}")
    
    # Test case 3: "3번째"
    print("\n=== Test 3: '3번째' ===")
    result = await entity_agent.analyze_user_intent(
        user_input="3번째",
        current_stage="security_medium_registration",
        stage_info=stage_info,
        collected_info={}
    )
    print(f"Extracted info: {result.get('extracted_info')}")
    
    print("\n✅ Tests completed!")
    print("Note: The actual ordinal mapping is handled in scenario_logic.py")
    print("Expected mappings:")
    print("  - 첫번째/1번째 → futuretech_19284019384")
    print("  - 두번째/2번째 → comas_rsa_12930295")
    print("  - 세번째/3번째 → security_card")
    print("  - 네번째/4번째 → shinhan_otp")

if __name__ == "__main__":
    asyncio.run(test_ordinal_choice_mapping())