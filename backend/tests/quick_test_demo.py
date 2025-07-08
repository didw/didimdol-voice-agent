#!/usr/bin/env python3
"""
Quick demonstration of the comprehensive testing framework for 디딤돌 voice agent.

This script provides a simple way to verify that the testing framework is properly
set up and demonstrates key testing capabilities.
"""

import asyncio
import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from test_answer_validation import AnswerValidator, ValidationResult
from test_realistic_scenarios import RealisticScenarioValidator


def demo_answer_validation():
    """Demonstrate the answer validation system."""
    print("🔍 Testing Answer Validation System")
    print("=" * 50)
    
    validator = AnswerValidator()
    
    # Test excellent response
    excellent_response = (
        "디딤돌 대출은 만39세 이하 청년층을 위한 생애최초 주택담보대출로, "
        "정부지원을 받아 저금리로 제공됩니다. 기본 금리는 연 2.5%부터 시작하며, "
        "소득수준에 따라 우대금리가 적용됩니다. 자세한 상담을 도와드리겠습니다."
    )
    
    print("\n📝 Testing Excellent Response:")
    print(f"Response: {excellent_response[:80]}...")
    
    result = validator.validate_response(excellent_response, 'didimdol_basic_info')
    
    print(f"\n📊 Validation Results:")
    print(f"   Overall Score: {result.score:.2f}/1.0")
    print(f"   Result: {result.result.value}")
    print(f"   Criteria Met: {len(result.criteria_met)}")
    print(f"   Criteria Failed: {len(result.criteria_failed)}")
    
    if result.criteria_met:
        print(f"\n✅ Successful Criteria:")
        for criterion in result.criteria_met[:3]:  # Show first 3
            print(f"   - {criterion}")
    
    if result.criteria_failed:
        print(f"\n❌ Failed Criteria:")
        for criterion in result.criteria_failed:
            print(f"   - {criterion}")
    
    # Test poor response
    poor_response = "몰라요"
    
    print(f"\n📝 Testing Poor Response:")
    print(f"Response: {poor_response}")
    
    poor_result = validator.validate_response(poor_response, 'didimdol_basic_info')
    
    print(f"\n📊 Validation Results:")
    print(f"   Overall Score: {poor_result.score:.2f}/1.0")
    print(f"   Result: {poor_result.result.value}")
    print(f"   Issues: {len(poor_result.criteria_failed)} criteria failed")


def demo_realistic_scenario_validation():
    """Demonstrate realistic scenario validation."""
    print("\n\n🎭 Testing Realistic Scenario Validation")
    print("=" * 50)
    
    validator = RealisticScenarioValidator()
    
    # Test response for 디딤돌 basic info
    response = (
        "디딤돌 대출은 청년층을 위한 정부 지원 대출상품입니다. "
        "만39세 이하 생애최초 주택구입자가 대상이며, "
        "저금리로 주택 구입을 지원합니다."
    )
    
    print(f"\n📝 Testing Response:")
    print(f"Response: {response}")
    
    # Validate different aspects
    validation = validator.validate_response(response, 'basic_info', 'didimdol')
    
    print(f"\n📊 Validation Results:")
    print(f"   Valid: {validation['valid']}")
    print(f"   Found Keywords: {validation['found_keywords']}")
    print(f"   Expected Keywords: {validation['expected_keywords']}")
    print(f"   Coverage: {validation['coverage']:.1%}")
    
    # Test politeness
    is_polite = validator.validate_politeness(response)
    print(f"   Polite Korean: {'✅' if is_polite else '❌'}")
    
    # Test completeness
    is_complete = validator.validate_completeness(response, 'basic_info')
    print(f"   Complete Answer: {'✅' if is_complete else '❌'}")


def demo_korean_language_patterns():
    """Demonstrate Korean language pattern testing."""
    print("\n\n🇰🇷 Testing Korean Language Patterns")
    print("=" * 50)
    
    validator = RealisticScenarioValidator()
    
    test_cases = [
        ("formal_polite", "디딤돌 대출에 대해 안내해 드리겠습니다."),
        ("informal_polite", "디딤돌 대출 정보를 알려드려요."),
        ("casual", "디딤돌 대출 정보야."),
        ("rude", "디딤돌 대출 정보다."),
    ]
    
    print("\n📝 Testing Different Politeness Levels:")
    
    for level, text in test_cases:
        is_polite = validator.validate_politeness(text)
        status = "✅ Polite" if is_polite else "❌ Not Polite"
        print(f"   {level:15} | {status:12} | {text}")


def demo_number_handling():
    """Demonstrate number and currency handling."""
    print("\n\n💰 Testing Number and Currency Handling")
    print("=" * 50)
    
    test_cases = [
        "금리는 연 2.5%입니다.",
        "한도는 최대 4억원까지 가능합니다.",
        "오천만원 대출이 가능합니다.",
        "연봉 4천만원이면 신청 가능합니다.",
        "금리 정보가 없습니다.",  # No numbers
    ]
    
    validator = AnswerValidator()
    
    print("\n📝 Testing Number Recognition:")
    
    for text in test_cases:
        # Test if response contains numbers
        import re
        number_pattern = r'[\d%.]+|[일이삼사오육칠팔구십백천만억]'
        has_numbers = bool(re.search(number_pattern, text))
        
        status = "✅ Contains Numbers" if has_numbers else "❌ No Numbers"
        print(f"   {status:18} | {text}")


def main():
    """Run comprehensive testing demonstration."""
    print("🧪 디딤돌 Voice Agent - Testing Framework Demo")
    print("=" * 60)
    print("This demo showcases key testing capabilities:\n")
    
    try:
        # Run all demos
        demo_answer_validation()
        demo_realistic_scenario_validation()
        demo_korean_language_patterns()
        demo_number_handling()
        
        print("\n\n🎉 Demo Completed Successfully!")
        print("=" * 60)
        print("✅ Answer validation system working")
        print("✅ Realistic scenario validation working")
        print("✅ Korean language pattern recognition working")
        print("✅ Number and currency handling working")
        print("\n💡 To run the full test suite:")
        print("   python tests/comprehensive_test_runner.py")
        print("\n📚 For more information, see:")
        print("   - README_TESTING.md")
        print("   - backend/tests/TESTING_SUMMARY.md")
        
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        print("\n🔧 Troubleshooting:")
        print("   1. Make sure you're in the backend directory")
        print("   2. Install test dependencies: pip install -r requirements-test.txt")
        print("   3. Check that all test files are present")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())