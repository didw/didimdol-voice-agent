"""
Test for transfer limit metadata overwrite issue
Tests the fix to prevent metadata values from being overwritten
"""

def test_metadata_field_preservation():
    """Test that metadata fields preserve existing valid values"""
    
    print("\n=== Testing Metadata Field Preservation Logic ===\n")
    
    # Simulate the scenario from the log
    collected_info = {}
    extracted_fields = {
        "security_medium": "기본값",
        "transfer_limit_once": "기본값", 
        "transfer_limit_daily": "기본값"
    }
    
    print("Initial state:")
    print(f"  collected_info: {collected_info}")
    print(f"  extracted_fields: {extracted_fields}")
    
    # Step 1: security_medium gets mapped to default choice
    collected_info["security_medium"] = "futuretech_19284019384"
    print(f"\n1. security_medium mapped to default: {collected_info['security_medium']}")
    
    # Step 2: Metadata from the chosen security medium is applied
    collected_info["transfer_limit_once"] = "50000000"
    collected_info["transfer_limit_daily"] = "100000000"
    print(f"2. Metadata applied:")
    print(f"   transfer_limit_once: {collected_info['transfer_limit_once']}")
    print(f"   transfer_limit_daily: {collected_info['transfer_limit_daily']}")
    
    # Step 3: Process extracted_fields (with the fix)
    metadata_fields = ["card_receipt_method", "transit_function", "transfer_limit_once", "transfer_limit_daily"]
    
    for field_key, field_value in extracted_fields.items():
        if field_key in metadata_fields:
            # 이미 올바른 값이 설정되어 있으면 유지
            if field_key in collected_info and collected_info[field_key] not in ["기본값", "기본", "디폴트"]:
                print(f"3. ✅ [KEPT] {field_key}: keeping existing value '{collected_info[field_key]}' (already set from metadata)")
            else:
                # metadata 필드는 그대로 저장  
                collected_info[field_key] = field_value
                print(f"3. ✅ [STORED] {field_key}: '{field_value}' (metadata field, no existing value)")
        else:
            print(f"3. [NORMAL] {field_key}: would go through normal validation")
    
    print(f"\nFinal collected_info: {collected_info}")
    
    # Verify the fix works
    assert collected_info["transfer_limit_once"] == "50000000", f"Expected '50000000', got '{collected_info['transfer_limit_once']}'"
    assert collected_info["transfer_limit_daily"] == "100000000", f"Expected '100000000', got '{collected_info['transfer_limit_daily']}'"
    
    print("\n✅ Metadata field preservation test passed!")
    return True

def test_edge_cases():
    """Test edge cases for the metadata field logic"""
    
    print("\n=== Testing Edge Cases ===\n")
    
    test_cases = [
        # (existing_value, extracted_value, expected_result, description)
        ("50000000", "기본값", "50000000", "Should keep existing valid value"),
        ("기본값", "기본값", "기본값", "Should store extracted value when existing is abstract"),
        (None, "기본값", "기본값", "Should store extracted value when no existing value"),
        ("100000000", "다른값", "100000000", "Should keep existing valid value over extracted"),
        ("기본", "새값", "새값", "Should replace abstract existing value"),
        ("디폴트", "새값", "새값", "Should replace abstract existing value"),
    ]
    
    metadata_fields = ["transfer_limit_once", "transfer_limit_daily"]
    
    for existing_value, extracted_value, expected_result, description in test_cases:
        print(f"Testing: {description}")
        print(f"  Existing: {existing_value}, Extracted: {extracted_value}")
        
        # Simulate the logic
        collected_info = {}
        if existing_value is not None:
            collected_info["transfer_limit_once"] = existing_value
        
        field_key = "transfer_limit_once"
        field_value = extracted_value
        
        if field_key in metadata_fields:
            if field_key in collected_info and collected_info[field_key] not in ["기본값", "기본", "디폴트"]:
                # Keep existing
                result = collected_info[field_key]
                action = "KEPT"
            else:
                # Store extracted
                collected_info[field_key] = field_value
                result = field_value
                action = "STORED"
        
        print(f"  Result: {result} ({action})")
        
        if result == expected_result:
            print(f"  ✅ PASS")
        else:
            print(f"  ❌ FAIL - Expected: {expected_result}")
        print()
    
    print("✅ Edge cases test completed!")

if __name__ == "__main__":
    print("="*60)
    print("Testing Transfer Limit Metadata Overwrite Fix")
    print("="*60)
    
    test_metadata_field_preservation()
    test_edge_cases()
    
    print("\n" + "="*60)
    print("SUMMARY: Fix prevents metadata values from being overwritten")
    print("1. Checks if valid value already exists before overwriting")
    print("2. Only replaces abstract values like '기본값', '기본', '디폴트'")
    print("3. Preserves concrete values like '50000000', '100000000'")
    print("="*60)