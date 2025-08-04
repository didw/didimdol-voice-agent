"""
Test for ordinal keywords recognition in scenario JSON
"""

import asyncio
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.graph.nodes.workers.intent_mapping import map_user_intent_to_choice

async def test_ordinal_keywords():
    """Test that ordinal keywords in JSON are correctly recognized"""
    
    print("\n=== Test 1: select_services with '첫번째' ===")
    choices = [
        {
            "display": "입출금 계좌 + 체크카드 + 모바일 뱅킹",
            "value": "all",
            "default": True,
            "keywords": ["모두", "전부", "다", "네", "좋아", "응"],
            "ordinal_keywords": ["첫번째", "1번째", "첫 번째", "1번", "첫째", "하나", "일번"]
        },
        {
            "display": "입출금 계좌 + 모바일 뱅킹",
            "value": "mobile_only",
            "keywords": ["모바일", "앱", "모바일만", "앱만"],
            "ordinal_keywords": ["두번째", "2번째", "두 번째", "2번", "둘째", "둘", "이번"]
        },
        {
            "display": "입출금 계좌 + 체크카드",
            "value": "card_only",
            "keywords": ["체크카드", "카드", "카드만", "체크카드만"],
            "ordinal_keywords": ["세번째", "3번째", "세 번째", "3번", "셋째", "셋", "삼번"]
        },
        {
            "display": "입출금 계좌",
            "value": "account_only",
            "keywords": ["계좌만", "입출금만", "아니", "아니요"],
            "ordinal_keywords": ["네번째", "4번째", "네 번째", "4번", "넷째", "넷", "사번"]
        }
    ]
    
    result = await map_user_intent_to_choice(
        user_input="첫번째",
        choices=choices,
        field_key="services_selected",
        keyword_mapping=None,
        current_stage_info={"stage_id": "select_services"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "all", f"Expected 'all' but got {result}"
    print("✅ Test 1 passed - '첫번째' correctly mapped to 'all'")
    
    # Test 2: '두번째'
    print("\n=== Test 2: '두번째' ===")
    result = await map_user_intent_to_choice(
        user_input="두번째",
        choices=choices,
        field_key="services_selected",
        keyword_mapping=None,
        current_stage_info={"stage_id": "select_services"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "mobile_only", f"Expected 'mobile_only' but got {result}"
    print("✅ Test 2 passed - '두번째' correctly mapped to 'mobile_only'")
    
    # Test 3: '3번째'
    print("\n=== Test 3: '3번째' ===")
    result = await map_user_intent_to_choice(
        user_input="3번째",
        choices=choices,
        field_key="services_selected",
        keyword_mapping=None,
        current_stage_info={"stage_id": "select_services"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "card_only", f"Expected 'card_only' but got {result}"
    print("✅ Test 3 passed - '3번째' correctly mapped to 'card_only'")
    
    # Test 4: '넷째'
    print("\n=== Test 4: '넷째' ===")
    result = await map_user_intent_to_choice(
        user_input="넷째",
        choices=choices,
        field_key="services_selected",
        keyword_mapping=None,
        current_stage_info={"stage_id": "select_services"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "account_only", f"Expected 'account_only' but got {result}"
    print("✅ Test 4 passed - '넷째' correctly mapped to 'account_only'")
    
    # Test 5: Test card selection with 5 choices
    print("\n=== Test 5: card_selection with '다섯번째' ===")
    card_choices = [
        {
            "display": "S-Line 체크카드 (후불교통)",
            "value": "sline_transit",
            "ordinal_keywords": ["첫번째", "1번째", "첫 번째", "1번", "첫째", "하나", "일번"]
        },
        {
            "display": "S-Line 체크카드 (일반)",
            "value": "sline_regular",
            "ordinal_keywords": ["두번째", "2번째", "두 번째", "2번", "둘째", "둘", "이번"]
        },
        {
            "display": "신한 Deep Dream 체크카드 (후불교통)",
            "value": "deepdream_transit",
            "ordinal_keywords": ["세번째", "3번째", "세 번째", "3번", "셋째", "셋", "삼번"]
        },
        {
            "display": "신한 Deep Dream 체크카드 (일반)",
            "value": "deepdream_regular",
            "ordinal_keywords": ["네번째", "4번째", "네 번째", "4번", "넷째", "넷", "사번"]
        },
        {
            "display": "신한카드 Hey Young 체크카드 (일반)",
            "value": "heyyoung_regular",
            "ordinal_keywords": ["다섯번째", "5번째", "다섯 번째", "5번", "다섯째", "다섯", "오번"]
        }
    ]
    
    result = await map_user_intent_to_choice(
        user_input="다섯번째",
        choices=card_choices,
        field_key="card_selection",
        keyword_mapping=None,
        current_stage_info={"stage_id": "card_selection"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "heyyoung_regular", f"Expected 'heyyoung_regular' but got {result}"
    print("✅ Test 5 passed - '다섯번째' correctly mapped to 'heyyoung_regular'")
    
    print("\n✅ All tests passed!")
    print("\nOrdinal keywords are correctly recognized from scenario JSON.")

if __name__ == "__main__":
    asyncio.run(test_ordinal_keywords())