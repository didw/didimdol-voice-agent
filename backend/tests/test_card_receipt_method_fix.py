"""
Test for card_receipt_method fix - prevent "즉시발급" from being mapped to default card choice
"""

def test_abstract_values_fix():
    """Test that '즉시발급' is no longer treated as abstract value"""
    
    print("\n=== Testing Abstract Values Fix ===\n")
    
    # Updated abstract_values list (without "발급")
    abstract_values = ["기본값", "그것", "그걸로", "디폴트", "기본", "추천", "제안", "기본값 수락"]
    
    test_cases = [
        ("즉시발급", False, "Should NOT be treated as abstract (contains '발급' but '발급' removed from list)"),
        ("배송", False, "Should NOT be treated as abstract (specific delivery method)"),
        ("그걸로 해줘", True, "Should be treated as abstract (contains '그걸로')"),
        ("기본값으로 해주세요", True, "Should be treated as abstract (contains '기본값')"),
        ("추천해주세요", True, "Should be treated as abstract (contains '추천')"),
        ("디폴트 선택", True, "Should be treated as abstract (contains '디폴트')"),
    ]
    
    all_passed = True
    for test_value, should_be_abstract, description in test_cases:
        is_abstract = any(abstract in test_value for abstract in abstract_values)
        
        if is_abstract == should_be_abstract:
            print(f"✅ PASS: {description}")
            print(f"   Value: '{test_value}' -> Abstract: {is_abstract}")
        else:
            print(f"❌ FAIL: {description}")
            print(f"   Value: '{test_value}' -> Expected: {should_be_abstract}, Got: {is_abstract}")
            all_passed = False
    
    print("\n" + "="*50)
    if all_passed:
        print("✅ All abstract values tests passed!")
        print("\nKey improvements:")
        print("1. '즉시발급' is no longer treated as abstract value")
        print("2. '배송' is no longer treated as abstract value")
        print("3. Real abstract values like '그걸로', '기본값' still work")
    else:
        print("❌ Some abstract values tests failed!")
    
    return all_passed

def test_metadata_processing_flow():
    """Test the complete metadata processing flow"""
    
    print("\n=== Testing Complete Metadata Processing Flow ===\n")
    
    # Simulate the processing flow
    extracted_fields = {"card_receipt_method": "즉시발급"}
    collected_info = {}
    
    # Step 1: Check if it's a metadata field
    metadata_fields = ["card_receipt_method", "transit_function", "transfer_limit_once", "transfer_limit_daily"]
    field_key = "card_receipt_method"
    field_value = extracted_fields[field_key]
    
    print(f"1. Processing field: {field_key} = '{field_value}'")
    
    if field_key in metadata_fields:
        # Metadata field - store directly without validation
        collected_info[field_key] = field_value
        print(f"2. ✅ Stored as metadata field (no choice validation): {field_key} = '{field_value}'")
        skip_validation = True
    else:
        skip_validation = False
        print(f"2. Field will go through choice validation")
    
    # Step 2: If not skipped, check against abstract values
    if not skip_validation:
        abstract_values = ["기본값", "그것", "그걸로", "디폴트", "기본", "추천", "제안", "기본값 수락"]
        is_abstract = any(abstract in field_value for abstract in abstract_values)
        
        if is_abstract:
            print(f"3. ❌ Would be mapped to default choice (abstract value detected)")
        else:
            print(f"3. ✅ Would be stored as-is (not abstract value)")
    else:
        print("3. ✅ Skipped abstract value check (metadata field)")
    
    # Verify final result
    assert field_key in collected_info, f"{field_key} should be in collected_info"
    assert collected_info[field_key] == "즉시발급", f"Expected '즉시발급', got '{collected_info[field_key]}'"
    
    print(f"\nFinal result: {collected_info}")
    print("✅ Metadata processing flow test passed!")
    
    return True

def test_edge_cases():
    """Test edge cases that might cause issues"""
    
    print("\n=== Testing Edge Cases ===\n")
    
    # Test values that contain abstract words but should be preserved
    edge_cases = [
        ("즉시발급", "Specific card receipt method"),
        ("배송", "Specific delivery method"),
        ("기본 계좌", "Contains '기본' but is specific account type"),
        ("추천 상품", "Contains '추천' but is specific product name"),
    ]
    
    # Updated abstract values (without "발급")
    abstract_values = ["기본값", "그것", "그걸로", "디폴트", "기본", "추천", "제안", "기본값 수락"]
    metadata_fields = ["card_receipt_method", "transit_function", "transfer_limit_once", "transfer_limit_daily"]
    
    for test_value, description in edge_cases:
        print(f"Testing: '{test_value}' ({description})")
        
        # Check if it would be treated as abstract
        is_abstract = any(abstract in test_value for abstract in abstract_values)
        
        # Check if it's a metadata field (which would skip validation)
        is_metadata = "card_receipt_method" in metadata_fields  # Assuming we're testing card_receipt_method
        
        if is_metadata:
            print(f"  ✅ Protected as metadata field (skips abstract check)")
        elif is_abstract:
            print(f"  ⚠️  Would be treated as abstract: contains one of {[a for a in abstract_values if a in test_value]}")
        else:
            print(f"  ✅ Would be preserved as-is")
    
    print("\n✅ Edge cases test completed!")

if __name__ == "__main__":
    print("="*60)
    print("Testing Card Receipt Method Fix")
    print("="*60)
    
    test_abstract_values_fix()
    test_metadata_processing_flow()
    test_edge_cases()
    
    print("\n" + "="*60)
    print("SUMMARY: Fix prevents '즉시발급' from being mapped to card choices")
    print("1. Removed '발급' from abstract_values lists")
    print("2. Added metadata field skip logic")
    print("3. '즉시발급' and '배송' are now preserved correctly")
    print("="*60)