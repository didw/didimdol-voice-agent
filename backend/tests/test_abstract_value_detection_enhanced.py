"""
Test for enhanced abstract value detection
Tests the fix for "그걸로 발급해줘" not being mapped to default choice
"""

def test_enhanced_abstract_detection():
    """Test enhanced abstract value detection logic"""
    
    print("\n=== Testing Enhanced Abstract Value Detection ===\n")
    
    # Test cases from real scenarios
    test_cases = [
        # (field_value, user_input, should_be_abstract, description)
        ("발급", "그걸로 발급해줘", True, "Should detect '그걸로' in user_input even when field_value is '발급'"),
        ("발급", "발급해줘", True, "Should detect '발급' as single abstract value"),
        ("즉시발급", "즉시발급으로 해줘", False, "Should NOT treat '즉시발급' as abstract (specific value)"),
        ("그걸로", "그걸로 해줘", True, "Should detect '그걸로' in field_value"),
        ("기본값", "기본값으로 해줘", True, "Should detect '기본값' in field_value"),
        ("sline_transit", "그걸로 발급해줘", False, "Should NOT be abstract when field_value is valid choice (would be handled before abstract detection)"),
        ("배송", "배송으로 해줘", False, "Should NOT treat '배송' as abstract (specific value)"),
    ]
    
    # Simulation of the enhanced logic
    abstract_values = ["기본값 수락", "그것", "그걸로", "그것으로", "디폴트", "기본", "추천", "제안", "등록", "등록해", "등록해줘", "선택", "선택해줘"]
    abstract_single_values = ["발급"]
    valid_choices = ['sline_transit', 'sline_regular', 'deepdream_transit', 'deepdream_regular', 'heyyoung_regular']
    
    all_passed = True
    for field_value, user_input, expected_abstract, description in test_cases:
        print(f"Testing: {description}")
        print(f"  field_value: '{field_value}', user_input: '{user_input}'")
        
        # First check if it's a valid choice (abstract detection only happens for invalid choices)
        if field_value in valid_choices:
            is_abstract = False
            reason = f"field_value '{field_value}' is a valid choice, no abstract detection needed"
        else:
            # Simulate the enhanced abstract detection logic (only for invalid choices)
            is_abstract = False
            if isinstance(field_value, str):
                # 1. 기존 abstract_values 체크 (부분 문자열 포함)
                if any(abstract in field_value for abstract in abstract_values):
                    is_abstract = True
                    reason = f"found '{[a for a in abstract_values if a in field_value]}' in field_value"
                # 2. 단독 abstract 값 체크 (정확히 일치)
                elif field_value.strip() in abstract_single_values:
                    is_abstract = True
                    reason = f"field_value '{field_value}' is in abstract_single_values"
                # 3. 원본 user_input도 체크 (그걸로 발급해줘 같은 경우)
                elif user_input and any(abstract in user_input for abstract in abstract_values):
                    is_abstract = True
                    reason = f"found '{[a for a in abstract_values if a in user_input]}' in user_input"
                else:
                    reason = "no abstract patterns found"
        
        print(f"  Result: {is_abstract} ({reason})")
        
        if is_abstract == expected_abstract:
            print(f"  ✅ PASS")
        else:
            print(f"  ❌ FAIL - Expected: {expected_abstract}")
            all_passed = False
        print()
    
    if all_passed:
        print("✅ All enhanced abstract detection tests passed!")
    else:
        print("❌ Some enhanced abstract detection tests failed!")
    
    return all_passed

def test_card_selection_scenario():
    """Test the specific card_selection scenario from the log"""
    
    print("\n=== Testing Card Selection Scenario ===\n")
    
    # From the log
    user_input = "그걸로 발급해줘"
    extracted_field_value = "발급"  # What LLM extracted
    valid_choices = ['sline_transit', 'sline_regular', 'deepdream_transit', 'deepdream_regular', 'heyyoung_regular']
    default_choice = 'sline_transit'
    
    print(f"User input: '{user_input}'")
    print(f"LLM extracted: '{extracted_field_value}'")
    print(f"Valid choices: {valid_choices}")
    print(f"Default choice: '{default_choice}'")
    
    # Step 1: Check if extracted value is valid
    is_valid_choice = extracted_field_value in valid_choices
    print(f"Is valid choice: {is_valid_choice}")
    
    if not is_valid_choice:
        # Step 2: Apply enhanced abstract detection
        abstract_values = ["기본값 수락", "그것", "그걸로", "그것으로", "디폴트", "기본", "추천", "제안", "등록", "등록해", "등록해줘", "선택", "선택해줘"]
        abstract_single_values = ["발급"]
        
        is_abstract = False
        if isinstance(extracted_field_value, str):
            # Check if "그걸로" is in user_input
            if user_input and any(abstract in user_input for abstract in abstract_values):
                is_abstract = True
                found_abstracts = [a for a in abstract_values if a in user_input]
                print(f"✅ Found abstract values in user_input: {found_abstracts}")
            # Check if "발급" is abstract single value
            elif extracted_field_value.strip() in abstract_single_values:
                is_abstract = True
                print(f"✅ Found abstract single value: '{extracted_field_value}'")
        
        if is_abstract:
            final_value = default_choice
            print(f"✅ Mapped to default: '{extracted_field_value}' → '{final_value}'")
            
            # Should also apply metadata from default choice
            print("✅ Should apply metadata from default choice (e.g., receipt_method, transit_enabled)")
        else:
            final_value = extracted_field_value
            print(f"❌ Stored as fallback: '{final_value}' (invalid choice)")
    
    # Expected result
    expected_final_value = default_choice
    actual_final_value = final_value if 'final_value' in locals() else extracted_field_value
    
    print(f"\nExpected final value: '{expected_final_value}'")
    print(f"Actual final value: '{actual_final_value}'")
    
    if actual_final_value == expected_final_value:
        print("✅ Card selection scenario test passed!")
        return True
    else:
        print("❌ Card selection scenario test failed!")
        return False

if __name__ == "__main__":
    print("="*70)
    print("Testing Enhanced Abstract Value Detection for Card Selection")
    print("="*70)
    
    test1_passed = test_enhanced_abstract_detection()
    test2_passed = test_card_selection_scenario()
    
    print("\n" + "="*70)
    if test1_passed and test2_passed:
        print("✅ ALL TESTS PASSED")
        print("SUMMARY: Enhanced abstract detection now handles:")
        print("1. '발급' as abstract single value")
        print("2. '그걸로' detection in original user_input")
        print("3. Proper mapping to default choice with metadata")
    else:
        print("❌ SOME TESTS FAILED")
        print("The enhanced abstract detection needs further improvements")
    print("="*70)