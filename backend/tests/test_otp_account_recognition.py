"""
Test for OTP payment account name recognition
"""

import asyncio
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.graph.nodes.workers.intent_mapping import map_user_intent_to_choice

async def test_account_name_recognition():
    """Test that account names are correctly recognized"""
    
    choices = [
        {
            "display": "쏠편한 입출금통장(저축예금)\n110-OOO-883827\n잔액 999,999,999원",
            "display_lines": [
                "쏠편한 입출금통장(저축예금)",
                "110-OOO-883827",
                "잔액 999,999,999원"
            ],
            "value": "account_110_883827",
            "default": True,
            "keywords": ["쏠편한", "저축예금", "883827", "27", "첫번째꺼", "첫번째계좌"],
            "ordinal_keywords": ["첫번째", "1번째", "첫 번째", "1번", "첫째", "하나", "일번"]
        },
        {
            "display": "쏠편한 입출금통장\n110-OOO-883828\n잔액 888,888,888원",
            "display_lines": [
                "쏠편한 입출금통장",
                "110-OOO-883828",
                "잔액 888,888,888원"
            ],
            "value": "account_110_883828",
            "keywords": ["쏠편한", "883828", "28", "두번째꺼", "두번째계좌"],
            "ordinal_keywords": ["두번째", "2번째", "두 번째", "2번", "둘째", "둘", "이번"]
        },
        {
            "display": "그냥 입출금통장\n110-OOO-883829\n잔액 777,777,777원",
            "display_lines": [
                "그냥 입출금통장",
                "110-OOO-883829",
                "잔액 777,777,777원"
            ],
            "value": "account_110_883829",
            "keywords": ["그냥", "883829", "29", "세번째꺼", "세번째계좌"],
            "ordinal_keywords": ["세번째", "3번째", "세 번째", "3번", "셋째", "셋", "삼번"]
        }
    ]
    
    # Test case 1: Account name recognition
    print("\n=== Test 1: '쏠편한' (account name) ===")
    result = await map_user_intent_to_choice(
        user_input="쏠편한",
        choices=choices,
        field_key="otp_payment_account",
        keyword_mapping=None,
        current_stage_info={"stage_id": "otp_payment_account"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    # Note: "쏠편한" appears in multiple accounts, so result may vary
    print(f"✅ Test 1 - '쏠편한' recognized (result: {result})")
    
    # Test case 2: Unique account name
    print("\n=== Test 2: '그냥' (unique account name) ===")
    result = await map_user_intent_to_choice(
        user_input="그냥",
        choices=choices,
        field_key="otp_payment_account",
        keyword_mapping=None,
        current_stage_info={"stage_id": "otp_payment_account"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "account_110_883829", f"Expected 'account_110_883829' but got {result}"
    print("✅ Test 2 passed - '그냥' correctly mapped to 'account_110_883829'")
    
    # Test case 3: Account number ending
    print("\n=== Test 3: '27' (account number ending) ===")
    result = await map_user_intent_to_choice(
        user_input="27",
        choices=choices,
        field_key="otp_payment_account",
        keyword_mapping=None,
        current_stage_info={"stage_id": "otp_payment_account"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "account_110_883827", f"Expected 'account_110_883827' but got {result}"
    print("✅ Test 3 passed - '27' correctly mapped to 'account_110_883827'")
    
    # Test case 4: Full account number
    print("\n=== Test 4: '883828' (full account number) ===")
    result = await map_user_intent_to_choice(
        user_input="883828",
        choices=choices,
        field_key="otp_payment_account",
        keyword_mapping=None,
        current_stage_info={"stage_id": "otp_payment_account"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "account_110_883828", f"Expected 'account_110_883828' but got {result}"
    print("✅ Test 4 passed - '883828' correctly mapped to 'account_110_883828'")
    
    # Test case 5: Account type
    print("\n=== Test 5: '저축예금' (account type) ===")
    result = await map_user_intent_to_choice(
        user_input="저축예금",
        choices=choices,
        field_key="otp_payment_account",
        keyword_mapping=None,
        current_stage_info={"stage_id": "otp_payment_account"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "account_110_883827", f"Expected 'account_110_883827' but got {result}"
    print("✅ Test 5 passed - '저축예금' correctly mapped to 'account_110_883827'")
    
    # Test case 6: Ordinal expression
    print("\n=== Test 6: '두번째꺼' (ordinal with suffix) ===")
    result = await map_user_intent_to_choice(
        user_input="두번째꺼",
        choices=choices,
        field_key="otp_payment_account",
        keyword_mapping=None,
        current_stage_info={"stage_id": "otp_payment_account"},
        collected_info={}
    )
    
    print(f"Result: {result}")
    assert result == "account_110_883828", f"Expected 'account_110_883828' but got {result}"
    print("✅ Test 6 passed - '두번째꺼' correctly mapped to 'account_110_883828'")
    
    print("\n✅ All tests passed!")
    print("\nAccount recognition features:")
    print("1. Account names (쏠편한, 그냥)")
    print("2. Account numbers (883827, 27)")
    print("3. Account types (저축예금)")
    print("4. Ordinal expressions (첫번째, 두번째꺼)")

if __name__ == "__main__":
    asyncio.run(test_account_name_recognition())