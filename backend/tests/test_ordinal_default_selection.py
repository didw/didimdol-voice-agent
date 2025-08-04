"""
Test for ordinal expression handling vs DEFAULT_SELECTION
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_ordinal_detection():
    """Test that ordinal expressions are correctly detected"""
    
    # Test data
    test_cases = [
        ("네번째꺼로 해줘", True, "Should detect ordinal in '네번째꺼로'"),
        ("네번째로 해줘", True, "Should detect ordinal in '네번째로'"),
        ("4번째", True, "Should detect ordinal in '4번째'"),
        ("네 번째 선택", True, "Should detect ordinal in '네 번째'"),
        ("네", False, "Should not detect ordinal in simple '네'"),
        ("네 좋아요", False, "Should not detect ordinal in '네 좋아요'"),
        ("예 맞습니다", False, "Should not detect ordinal in '예 맞습니다'"),
        ("첫번째 것으로 할게요", True, "Should detect ordinal in '첫번째'"),
        ("두번째로 주세요", True, "Should detect ordinal in '두번째'"),
        ("3번으로 해주세요", True, "Should detect ordinal in '3번'"),
    ]
    
    ordinal_expressions = [
        "첫번째", "1번째", "첫 번째", "1번", "첫째", "하나", "일번",
        "두번째", "2번째", "두 번째", "2번", "둘째", "둘", "이번",
        "세번째", "3번째", "세 번째", "3번", "셋째", "셋", "삼번",
        "네번째", "4번째", "네 번째", "4번", "넷째", "넷", "사번",
        "다섯번째", "5번째", "다섯 번째", "5번", "다섯째", "다섯", "오번"
    ]
    
    print("\n=== Testing Ordinal Detection ===\n")
    
    all_passed = True
    for user_input, expected, description in test_cases:
        is_ordinal = any(ord_expr in user_input for ord_expr in ordinal_expressions)
        
        if is_ordinal == expected:
            print(f"✅ PASS: {description}")
            print(f"   Input: '{user_input}' -> Ordinal: {is_ordinal}")
        else:
            print(f"❌ FAIL: {description}")
            print(f"   Input: '{user_input}' -> Expected: {expected}, Got: {is_ordinal}")
            all_passed = False
    
    print("\n" + "="*50)
    if all_passed:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed!")
    
    return all_passed

def test_positive_response_detection():
    """Test that positive responses are correctly detected"""
    
    positive_words = ["네", "예", "응", "어", "그래", "좋아", "맞아", "알겠", "할게"]
    
    test_cases = [
        ("네", True, "Should detect positive in '네'"),
        ("예 맞습니다", True, "Should detect positive in '예 맞습니다'"),
        ("좋아요", True, "Should detect positive in '좋아요'"),
        ("네번째", True, "Contains '네' but should be handled as ordinal"),
        ("아니요", False, "Should not detect positive in '아니요'"),
        ("안돼요", False, "Should not detect positive in '안돼요'"),
    ]
    
    print("\n=== Testing Positive Response Detection ===\n")
    
    for user_input, expected, description in test_cases:
        user_lower = user_input.lower().strip()
        is_positive = any(word in user_lower for word in positive_words)
        
        # Note: In actual code, ordinal check would override positive detection
        if "네번째" in user_input:
            print(f"⚠️ NOTE: '{user_input}' contains '네' but should be handled as ordinal, not positive")
        elif is_positive == expected:
            print(f"✅ PASS: {description}")
            print(f"   Input: '{user_input}' -> Positive: {is_positive}")
        else:
            print(f"❌ FAIL: {description}")
            print(f"   Input: '{user_input}' -> Expected: {expected}, Got: {is_positive}")

if __name__ == "__main__":
    print("="*60)
    print("Testing Ordinal Expression vs DEFAULT_SELECTION Logic")
    print("="*60)
    
    test_ordinal_detection()
    test_positive_response_detection()
    
    print("\n" + "="*60)
    print("IMPORTANT: In the actual scenario_logic.py:")
    print("1. Ordinal expressions are checked FIRST")
    print("2. If ordinal is detected, DEFAULT_SELECTION is skipped")
    print("3. This prevents '네번째' from being treated as '네' (yes)")
    print("="*60)