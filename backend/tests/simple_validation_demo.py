#!/usr/bin/env python3
"""
Simple validation demo that shows the testing framework concepts
without requiring full dependencies.
"""

import re
from typing import Dict, List, Any
from enum import Enum


class ValidationResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"


class SimpleValidator:
    """Simplified version of our answer validation system for demo purposes."""
    
    def __init__(self):
        self.polite_markers = [
            '습니다', '세요', '십니다', '요', '해요', 
            '드려요', '드립니다', '해드려요'
        ]
        
        self.didimdol_keywords = [
            '디딤돌', '청년', '생애최초', '주택담보대출', 
            '정부지원', '만39세', '저금리'
        ]
        
        self.financial_terms = [
            '금리', '한도', '대출', '신청', '조건', '서류'
        ]
    
    def validate_response(self, response: str, category: str) -> Dict[str, Any]:
        """Validate a response and return detailed results."""
        score = 0.0
        criteria_met = []
        criteria_failed = []
        
        # 1. Length check
        if 20 <= len(response) <= 500:
            criteria_met.append("✅ Appropriate length")
            score += 0.2
        else:
            criteria_failed.append("❌ Length not appropriate")
        
        # 2. Politeness check
        if any(marker in response for marker in self.polite_markers):
            criteria_met.append("✅ Uses polite Korean")
            score += 0.2
        else:
            criteria_failed.append("❌ Lacks polite Korean markers")
        
        # 3. Keyword relevance
        if category == 'didimdol':
            found_keywords = [kw for kw in self.didimdol_keywords if kw in response]
            if found_keywords:
                criteria_met.append(f"✅ Contains relevant keywords: {found_keywords}")
                score += 0.2
            else:
                criteria_failed.append("❌ Missing relevant keywords")
        
        # 4. Financial terminology
        found_financial = [term for term in self.financial_terms if term in response]
        if found_financial:
            criteria_met.append(f"✅ Uses financial terminology: {found_financial}")
            score += 0.2
        else:
            criteria_failed.append("❌ Lacks financial terminology")
        
        # 5. Number information (for rate/amount questions)
        number_pattern = r'[\d%.]+|[일이삼사오육칠팔구십백천만억]'
        if re.search(number_pattern, response):
            criteria_met.append("✅ Includes numerical information")
            score += 0.2
        else:
            # Only penalize if numbers are expected
            if any(term in response.lower() for term in ['금리', '한도', '율', '원']):
                criteria_failed.append("❌ Missing expected numerical data")
        
        # Determine overall result
        if score >= 0.8:
            result = ValidationResult.PASS
        elif score >= 0.6:
            result = ValidationResult.WARNING
        else:
            result = ValidationResult.FAIL
        
        return {
            'result': result,
            'score': score,
            'criteria_met': criteria_met,
            'criteria_failed': criteria_failed,
            'response_length': len(response)
        }


def demo_validation_system():
    """Demonstrate the validation system with various responses."""
    print("🧪 디딤돌 Voice Agent - Validation System Demo")
    print("=" * 60)
    
    validator = SimpleValidator()
    
    test_responses = [
        {
            'name': 'Excellent Response',
            'text': '디딤돌 대출은 만39세 이하 청년층을 위한 생애최초 주택담보대출로, '
                   '정부지원을 받아 연 2.5% 저금리로 제공됩니다. 자세한 상담을 도와드리겠습니다.',
            'category': 'didimdol'
        },
        {
            'name': 'Good Response',
            'text': '디딤돌 대출은 청년을 위한 대출상품입니다. 금리와 한도에 대해 안내해 드릴 수 있습니다.',
            'category': 'didimdol'
        },
        {
            'name': 'Poor Response - Too Short',
            'text': '네, 대출이에요.',
            'category': 'didimdol'
        },
        {
            'name': 'Poor Response - Impolite',
            'text': '디딤돌 대출은 청년 대출이다. 금리는 2.5%다.',
            'category': 'didimdol'
        },
        {
            'name': 'Missing Keywords',
            'text': '저희 은행에서 제공하는 주택 관련 금융상품이 있습니다. '
                   '자세한 내용을 안내해 드리겠습니다.',
            'category': 'didimdol'
        }
    ]
    
    print("\n📊 Testing Various Response Quality Levels:")
    print("-" * 60)
    
    for test_case in test_responses:
        print(f"\n🔍 {test_case['name']}:")
        print(f"   Text: {test_case['text'][:80]}...")
        
        validation = validator.validate_response(test_case['text'], test_case['category'])
        
        # Color code the result
        result_icon = {
            ValidationResult.PASS: "🟢",
            ValidationResult.WARNING: "🟡", 
            ValidationResult.FAIL: "🔴"
        }
        
        print(f"   {result_icon[validation['result']]} Result: {validation['result'].value}")
        print(f"   📈 Score: {validation['score']:.1f}/1.0")
        print(f"   📏 Length: {validation['response_length']} characters")
        
        if validation['criteria_met']:
            print(f"   ✅ Passed Criteria:")
            for criterion in validation['criteria_met']:
                print(f"      {criterion}")
        
        if validation['criteria_failed']:
            print(f"   ❌ Failed Criteria:")
            for criterion in validation['criteria_failed']:
                print(f"      {criterion}")


def demo_korean_language_validation():
    """Demonstrate Korean language specific validation."""
    print("\n\n🇰🇷 Korean Language Validation Demo")
    print("=" * 60)
    
    validator = SimpleValidator()
    
    test_cases = [
        {
            'level': 'Very Formal',
            'text': '디딤돌 대출에 대해 안내해 드리겠습니다.',
            'expected': 'PASS'
        },
        {
            'level': 'Polite',  
            'text': '디딤돌 대출 정보를 알려드려요.',
            'expected': 'PASS'
        },
        {
            'level': 'Casual',
            'text': '디딤돌 대출 정보야.',
            'expected': 'FAIL'
        },
        {
            'level': 'Rude',
            'text': '디딤돌 대출이다.',
            'expected': 'FAIL'
        }
    ]
    
    print("\n📝 Testing Korean Politeness Levels:")
    
    for case in test_cases:
        is_polite = any(marker in case['text'] for marker in validator.polite_markers)
        status = "✅ POLITE" if is_polite else "❌ IMPOLITE"
        expected = f"(Expected: {case['expected']})"
        
        print(f"   {case['level']:12} | {status:12} | {case['text']} {expected}")


def demo_realistic_scenarios():
    """Demonstrate realistic conversation scenarios."""
    print("\n\n🎭 Realistic Conversation Scenarios")
    print("=" * 60)
    
    validator = SimpleValidator()
    
    scenarios = [
        {
            'user': '디딤돌 대출이 뭔가요?',
            'agent': '디딤돌 대출은 만39세 이하 청년층을 위한 생애최초 주택담보대출입니다. '
                    '정부지원을 받아 저금리로 제공되며, 최대 4억원까지 대출이 가능합니다.',
            'scenario': 'Basic Information Inquiry'
        },
        {
            'user': '금리가 어떻게 되나요?',
            'agent': '디딤돌 대출의 기본 금리는 연 2.5%부터 시작하며, 소득수준에 따라 '
                    '우대금리가 적용됩니다.',
            'scenario': 'Interest Rate Inquiry'
        },
        {
            'user': '32살이고 연봉 4천만원인데 받을 수 있나요?',
            'agent': '네, 만39세 이하이고 연소득 7천만원 이하 조건을 충족하시므로 '
                    '디딤돌 대출 신청이 가능합니다. 추가 상담을 도와드리겠습니다.',
            'scenario': 'Personal Eligibility Assessment'
        }
    ]
    
    print("\n💬 Testing Realistic Conversation Patterns:")
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"\n   📍 Scenario {i}: {scenario['scenario']}")
        print(f"   👤 User: {scenario['user']}")
        print(f"   🤖 Agent: {scenario['agent'][:80]}...")
        
        validation = validator.validate_response(scenario['agent'], 'didimdol')
        result_icon = {
            ValidationResult.PASS: "🟢",
            ValidationResult.WARNING: "🟡",
            ValidationResult.FAIL: "🔴"
        }
        
        print(f"   {result_icon[validation['result']]} Quality: {validation['result'].value} "
              f"(Score: {validation['score']:.1f}/1.0)")


def main():
    """Run the complete validation demo."""
    try:
        demo_validation_system()
        demo_korean_language_validation()
        demo_realistic_scenarios()
        
        print("\n\n🎉 Demo Completed Successfully!")
        print("=" * 60)
        print("✅ Response validation working")
        print("✅ Korean language assessment working") 
        print("✅ Realistic scenario testing working")
        print("\n💡 This demo shows core concepts. The full framework includes:")
        print("   • Multi-turn conversation testing")
        print("   • Comprehensive edge case coverage")
        print("   • Automated test report generation")
        print("   • Performance benchmarking")
        print("   • Integration with actual agent code")
        print("\n📚 For complete documentation, see:")
        print("   • README_TESTING.md")
        print("   • backend/tests/TESTING_SUMMARY.md")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        return 1


if __name__ == "__main__":
    exit(main())