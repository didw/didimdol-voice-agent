"""
Test for '~만' (only) pattern handling in additional_services stage
"""

import asyncio
import json
from app.agents.entity_agent import EntityRecognitionAgent

async def test_only_pattern():
    """Test that '~만' pattern correctly sets other fields to False"""
    
    entity_agent = EntityRecognitionAgent()
    
    # Test case 1: "해외아이피만 해줘"
    print("\n=== Test 1: '해외아이피만 해줘' ===")
    stage_info = {
        "stage_id": "additional_services",
        "stage_name": "추가 정보 선택",
        "prompt": "중요거래 알림과 출금 알림, 해외 IP 이체 제한을 모두 신청해드릴까요?",
        "fields_to_collect": ["important_transaction_alert", "withdrawal_alert", "overseas_ip_restriction"]
    }
    
    result = await entity_agent.analyze_user_intent(
        user_input="해외아이피만 해줘",
        current_stage="additional_services",
        stage_info=stage_info,
        collected_info={}
    )
    
    print(f"Extracted info: {result.get('extracted_info')}")
    assert result.get('extracted_info', {}).get('overseas_ip_restriction') == True, "overseas_ip_restriction should be True"
    assert result.get('extracted_info', {}).get('important_transaction_alert') == False, "important_transaction_alert should be False"
    assert result.get('extracted_info', {}).get('withdrawal_alert') == False, "withdrawal_alert should be False"
    print("✅ Test 1 passed")
    
    # Test case 2: "중요거래만 알려줘"
    print("\n=== Test 2: '중요거래만 알려줘' ===")
    result = await entity_agent.analyze_user_intent(
        user_input="중요거래만 알려줘",
        current_stage="additional_services",
        stage_info=stage_info,
        collected_info={}
    )
    
    print(f"Extracted info: {result.get('extracted_info')}")
    assert result.get('extracted_info', {}).get('important_transaction_alert') == True, "important_transaction_alert should be True"
    assert result.get('extracted_info', {}).get('overseas_ip_restriction') == False, "overseas_ip_restriction should be False"
    assert result.get('extracted_info', {}).get('withdrawal_alert') == False, "withdrawal_alert should be False"
    print("✅ Test 2 passed")
    
    # Test case 3: "출금만 알려줘"
    print("\n=== Test 3: '출금만 알려줘' ===")
    result = await entity_agent.analyze_user_intent(
        user_input="출금만 알려줘",
        current_stage="additional_services",
        stage_info=stage_info,
        collected_info={}
    )
    
    print(f"Extracted info: {result.get('extracted_info')}")
    assert result.get('extracted_info', {}).get('withdrawal_alert') == True, "withdrawal_alert should be True"
    assert result.get('extracted_info', {}).get('important_transaction_alert') == False, "important_transaction_alert should be False"
    assert result.get('extracted_info', {}).get('overseas_ip_restriction') == False, "overseas_ip_restriction should be False"
    print("✅ Test 3 passed")
    
    print("\n✅ All tests passed!")

if __name__ == "__main__":
    asyncio.run(test_only_pattern())