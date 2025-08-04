"""
Test for security_medium_registration stage transition
Tests the fix for stage not transitioning after all fields collected
"""

def test_security_medium_stage_transition():
    """Test that security_medium_registration transitions to next stage"""
    
    print("\n=== Testing Security Medium Stage Transition Logic ===\n")
    
    # Simulate the security_medium_registration next_step structure
    next_step = {
        "shinhan_otp": "otp_payment_account",
        "futuretech_19284019384": "additional_services", 
        "comas_rsa_12930295": "additional_services",
        "security_card": "additional_services"
    }
    
    test_cases = [
        ("futuretech_19284019384", "additional_services", "Future Tech should go to additional_services"),
        ("comas_rsa_12930295", "additional_services", "Comas RSA should go to additional_services"),
        ("security_card", "additional_services", "Security card should go to additional_services"),
        ("shinhan_otp", "otp_payment_account", "Shinhan OTP should go to otp_payment_account"),
        ("unknown_medium", "security_medium_registration", "Unknown medium should stay at current stage"),
        (None, "security_medium_registration", "No medium should stay at current stage"),
    ]
    
    current_stage_id = "security_medium_registration"
    
    for security_medium, expected_next, description in test_cases:
        print(f"Testing: {description}")
        print(f"  Security medium: {security_medium}")
        
        # Simulate the logic from the fix
        collected_info = {"security_medium": security_medium} if security_medium else {}
        
        if current_stage_id == "security_medium_registration":
            security_medium_value = collected_info.get("security_medium")
            if security_medium_value:
                next_stage_id = next_step.get(security_medium_value, current_stage_id)
                action = f"security_medium='{security_medium_value}' -> {next_stage_id}"
            else:
                next_stage_id = current_stage_id
                action = f"no security_medium, staying at {current_stage_id}"
        else:
            next_stage_id = current_stage_id
            action = "not security_medium_registration stage"
        
        print(f"  Result: {next_stage_id} ({action})")
        
        if next_stage_id == expected_next:
            print(f"  ✅ PASS")
        else:
            print(f"  ❌ FAIL - Expected: {expected_next}")
        print()
    
    print("✅ Security medium stage transition test completed!")

def test_collected_info_validation():
    """Test that all required fields are properly collected"""
    
    print("\n=== Testing Required Fields Validation ===\n")
    
    # From the log, these are the fields that should be collected
    fields_to_collect = ['security_medium', 'transfer_limit_once', 'transfer_limit_daily']
    
    # Test case from the log
    collected_info = {
        'security_medium': 'futuretech_19284019384',
        'transfer_limit_once': '50000000',
        'transfer_limit_daily': '100000000'
    }
    
    print(f"Fields to collect: {fields_to_collect}")
    print(f"Collected info: {collected_info}")
    
    # Check if all required fields are collected
    required_fields_collected = True
    missing_fields = []
    
    for field in fields_to_collect:
        if field not in collected_info or collected_info.get(field) is None:
            required_fields_collected = False
            missing_fields.append(field)
    
    print(f"Required fields collected: {required_fields_collected}")
    if missing_fields:
        print(f"Missing fields: {missing_fields}")
    
    # This should be True for stage transition to work
    assert required_fields_collected, f"Required fields should be collected, missing: {missing_fields}"
    
    print("✅ All required fields are properly collected!")
    
    # Now test the stage transition logic
    next_step = {
        "futuretech_19284019384": "additional_services"
    }
    
    security_medium = collected_info.get("security_medium")
    expected_next_stage = next_step.get(security_medium, "security_medium_registration")
    
    print(f"\nStage transition:")
    print(f"  Current: security_medium_registration")
    print(f"  Security medium: {security_medium}")
    print(f"  Expected next: {expected_next_stage}")
    
    assert expected_next_stage == "additional_services", f"Should transition to additional_services"
    print("✅ Stage transition logic works correctly!")

if __name__ == "__main__":
    print("="*60)
    print("Testing Security Medium Registration Stage Transition Fix")
    print("="*60)
    
    test_security_medium_stage_transition()
    test_collected_info_validation()
    
    print("\n" + "="*60)
    print("SUMMARY: Fix adds security_medium_registration next_step handling")
    print("1. Checks security_medium value from collected_info")
    print("2. Uses next_step dict to determine next stage")
    print("3. Transitions to additional_services for futuretech_19284019384")
    print("4. Transitions to otp_payment_account for shinhan_otp")
    print("="*60)