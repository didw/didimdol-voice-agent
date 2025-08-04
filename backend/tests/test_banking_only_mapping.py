"""
Test for '뱅킹만' mapping to mobile_only instead of account_only
"""

import asyncio
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.entity_agent import EntityRecognitionAgent

async def test_banking_only_mapping():
    """Test that '뱅킹만' is correctly mapped to 'mobile_only'"""
    
    entity_agent = EntityRecognitionAgent()
    
    # Test case 1: "뱅킹만 해줘"
    print("\n=== Test 1: '뱅킹만 해줘' ===")
    stage_info = {
        "stage_id": "select_services",
        "stage_name": "필요 업무 확인",
        "prompt": "입출금 계좌는 한도계좌로만 가입할 수 있어요.\\n지금 만드시는 계좌를 모바일 앱과 체크카드로 함께 이용할 수 있도록 가입해 드릴까요?",
        "fields_to_collect": ["services_selected"],
        "extraction_prompt": "사용자가 선택한 서비스를 추출하세요:\\n- \"모두\", \"전부\", \"다\" → \"all\"\\n- \"모바일\", \"앱\", \"뱅킹\", \"뱅킹만\", \"모바일뱅킹\", \"인터넷뱅킹\" → \"mobile_only\"\\n- \"체크카드\", \"카드\" → \"card_only\"\\n- \"계좌만\", \"입출금만\" → \"account_only\"",
        "choices": [
            {
                "display": "입출금 계좌 + 체크카드 + 모바일 뱅킹",
                "value": "all",
                "default": True,
                "keywords": ["모두", "전부", "다", "네", "좋아", "응"]
            },
            {
                "display": "입출금 계좌 + 모바일 뱅킹",
                "value": "mobile_only",
                "keywords": ["모바일", "앱", "모바일만", "앱만", "뱅킹", "뱅킹만", "모바일뱅킹", "모바일뱅킹만", "인터넷뱅킹", "인터넷뱅킹만"]
            },
            {
                "display": "입출금 계좌 + 체크카드",
                "value": "card_only",
                "keywords": ["체크카드", "카드", "카드만", "체크카드만"]
            },
            {
                "display": "입출금 계좌",
                "value": "account_only",
                "keywords": ["계좌만", "입출금만", "아니", "아니요", "아니야", "싫어", "안해", "필요없어"]
            }
        ]
    }
    
    result = await entity_agent.analyze_user_intent(
        user_input="뱅킹만 해줘",
        current_stage="select_services",
        stage_info=stage_info,
        collected_info={}
    )
    
    print(f"Extracted info: {result.get('extracted_info')}")
    assert result.get('extracted_info', {}).get('services_selected') == 'mobile_only', f"Expected 'mobile_only' but got {result.get('extracted_info', {}).get('services_selected')}"
    print("✅ Test 1 passed - '뱅킹만' correctly mapped to 'mobile_only'")
    
    # Test case 2: "모바일뱅킹만"
    print("\n=== Test 2: '모바일뱅킹만' ===")
    result = await entity_agent.analyze_user_intent(
        user_input="모바일뱅킹만",
        current_stage="select_services",
        stage_info=stage_info,
        collected_info={}
    )
    
    print(f"Extracted info: {result.get('extracted_info')}")
    assert result.get('extracted_info', {}).get('services_selected') == 'mobile_only', f"Expected 'mobile_only' but got {result.get('extracted_info', {}).get('services_selected')}"
    print("✅ Test 2 passed - '모바일뱅킹만' correctly mapped to 'mobile_only'")
    
    # Test case 3: "인터넷뱅킹만 해주세요"
    print("\n=== Test 3: '인터넷뱅킹만 해주세요' ===")
    result = await entity_agent.analyze_user_intent(
        user_input="인터넷뱅킹만 해주세요",
        current_stage="select_services",
        stage_info=stage_info,
        collected_info={}
    )
    
    print(f"Extracted info: {result.get('extracted_info')}")
    assert result.get('extracted_info', {}).get('services_selected') == 'mobile_only', f"Expected 'mobile_only' but got {result.get('extracted_info', {}).get('services_selected')}"
    print("✅ Test 3 passed - '인터넷뱅킹만' correctly mapped to 'mobile_only'")
    
    # Test case 4: Make sure "계좌만" still maps to account_only
    print("\n=== Test 4: '계좌만' should still map to 'account_only' ===")
    result = await entity_agent.analyze_user_intent(
        user_input="계좌만",
        current_stage="select_services",
        stage_info=stage_info,
        collected_info={}
    )
    
    print(f"Extracted info: {result.get('extracted_info')}")
    assert result.get('extracted_info', {}).get('services_selected') == 'account_only', f"Expected 'account_only' but got {result.get('extracted_info', {}).get('services_selected')}"
    print("✅ Test 4 passed - '계좌만' correctly mapped to 'account_only'")
    
    print("\n✅ All tests passed!")

if __name__ == "__main__":
    asyncio.run(test_banking_only_mapping())