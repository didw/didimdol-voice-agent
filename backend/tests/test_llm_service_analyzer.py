#!/usr/bin/env python3

"""
LLM 기반 서비스 선택 분석기 테스트
"""

import asyncio
import sys
import os

# 프로젝트 루트를 Python path에 추가
sys.path.append('/Users/jyyang/Project/didimdol-voice-agent/backend')

async def test_service_selection_analyzer():
    """서비스 선택 분석기 종합 테스트"""
    try:
        from app.services.service_selection_analyzer import service_selection_analyzer
    except ImportError as e:
        print(f"❌ Import 실패: {e}")
        return False
    
    print("🧪 LLM 기반 서비스 선택 분석기 테스트")
    print("="*60)
    
    # 다양한 사용자 입력 케이스
    test_cases = [
        {
            "input": "둘다요",
            "expected_choice": "BOTH",
            "expected_normalized": "둘 다 신청",
            "description": "실제 발생 케이스"
        },
        {
            "input": "체크카드도 필요하고 인터넷뱅킹도 해주세요",
            "expected_choice": "BOTH", 
            "expected_normalized": "둘 다 신청",
            "description": "자연스러운 표현"
        },
        {
            "input": "카드만 있으면 돼요",
            "expected_choice": "CARD_ONLY",
            "expected_normalized": "체크카드만",
            "description": "간접적 체크카드 표현"
        },
        {
            "input": "온라인뱅킹만 신청할게요",
            "expected_choice": "BANKING_ONLY",
            "expected_normalized": "인터넷뱅킹만", 
            "description": "인터넷뱅킹 다른 표현"
        },
        {
            "input": "나중에 할게요",
            "expected_choice": "NONE",
            "expected_normalized": "아니요",
            "description": "간접적 거절"
        },
        {
            "input": "뭐가 좋을까요?",
            "expected_choice": "UNCLEAR",
            "expected_normalized": None,
            "description": "질문/불분명"
        },
        {
            "input": "네, 좋아요",
            "expected_choice": "UNCLEAR",
            "expected_normalized": None,
            "description": "애매한 긍정"
        }
    ]
    
    collected_info = {"use_lifelong_account": False}
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        user_input = test_case["input"]
        expected_choice = test_case["expected_choice"]
        expected_normalized = test_case["expected_normalized"]
        description = test_case["description"]
        
        print(f"\n{i}. {description}")
        print(f"   입력: '{user_input}'")
        
        try:
            # 종합 분석 실행
            normalized_value, next_stage_id, processing_info = await service_selection_analyzer.process_additional_services_input(
                user_input=user_input,
                collected_info=collected_info
            )
            
            # 결과 추출
            analysis = processing_info.get("analysis", {})
            actual_choice = analysis.get("choice", "UNKNOWN")
            confidence = analysis.get("confidence", 0.0)
            reasoning = analysis.get("reasoning", "")
            
            # 검증
            choice_match = actual_choice == expected_choice
            normalized_match = normalized_value == expected_normalized
            
            print(f"   분석 결과: {actual_choice} (신뢰도: {confidence:.2f})")
            print(f"   정규화 값: '{normalized_value}'")
            print(f"   다음 단계: {next_stage_id}")
            print(f"   추론: {reasoning}")
            
            status = "✅ 정확" if (choice_match and normalized_match) else "❌ 부정확"
            print(f"   검증: {status}")
            
            if not choice_match:
                print(f"     예상 선택: {expected_choice}, 실제: {actual_choice}")
            if not normalized_match:
                print(f"     예상 정규화: '{expected_normalized}', 실제: '{normalized_value}'")
            
            results.append({
                "input": user_input,
                "choice_match": choice_match,
                "normalized_match": normalized_match,
                "confidence": confidence
            })
            
        except Exception as e:
            print(f"   ❌ 오류: {e}")
            results.append({
                "input": user_input,
                "choice_match": False,
                "normalized_match": False,
                "confidence": 0.0
            })
    
    # 전체 결과 요약
    print("\n" + "="*60)
    print("📊 테스트 결과 요약")
    print("="*60)
    
    choice_accuracy = sum(1 for r in results if r["choice_match"]) / len(results) * 100
    normalized_accuracy = sum(1 for r in results if r["normalized_match"]) / len(results) * 100
    avg_confidence = sum(r["confidence"] for r in results) / len(results)
    
    print(f"선택 분석 정확도: {choice_accuracy:.1f}% ({sum(1 for r in results if r['choice_match'])}/{len(results)})")
    print(f"정규화 정확도: {normalized_accuracy:.1f}% ({sum(1 for r in results if r['normalized_match'])}/{len(results)})")
    print(f"평균 신뢰도: {avg_confidence:.2f}")
    
    success = choice_accuracy >= 80 and normalized_accuracy >= 80
    
    if success:
        print("🎉 LLM 기반 분석기가 성공적으로 작동합니다!")
        print("💡 키워드 기반 방식보다 훨씬 견고한 분석이 가능합니다.")
    else:
        print("⚠️ 일부 케이스에서 개선이 필요합니다.")
    
    return success

async def test_edge_cases():
    """엣지 케이스 테스트"""
    try:
        from app.services.service_selection_analyzer import service_selection_analyzer
    except ImportError:
        return False
    
    print("\n🔬 엣지 케이스 테스트")
    print("="*60)
    
    edge_cases = [
        "체크카드는 필요한데 인터넷뱅킹은 모르겠어요",
        "수수료가 있나요?",
        "어떤 차이가 있는지 알려주세요",
        "카드 발급 수수료는 얼마인가요?",
        "다른 은행과 비교하면 어때요?",
        "",  # 빈 입력
        "ㅇㅇ",  # 의미 없는 입력
    ]
    
    for i, user_input in enumerate(edge_cases, 1):
        print(f"\n{i}. 엣지 케이스: '{user_input}'")
        
        try:
            normalized_value, next_stage_id, processing_info = await service_selection_analyzer.process_additional_services_input(
                user_input=user_input,
                collected_info={}
            )
            
            analysis = processing_info.get("analysis", {})
            choice = analysis.get("choice", "UNKNOWN")
            confidence = analysis.get("confidence", 0.0)
            
            print(f"   결과: {choice} (신뢰도: {confidence:.2f})")
            print(f"   정규화: '{normalized_value}'")
            print(f"   다음 단계: {next_stage_id}")
            
            # 엣지 케이스는 대부분 UNCLEAR이어야 함
            is_appropriate = choice == "UNCLEAR" or confidence < 0.7
            status = "✅ 적절" if is_appropriate else "⚠️ 확인 필요"
            print(f"   평가: {status}")
            
        except Exception as e:
            print(f"   ❌ 오류: {e}")

if __name__ == "__main__":
    async def main():
        print("🚀 LLM 기반 서비스 선택 분석기 종합 테스트")
        print("="*60)
        
        # 1. 기본 기능 테스트
        basic_success = await test_service_selection_analyzer()
        
        # 2. 엣지 케이스 테스트
        await test_edge_cases()
        
        print("\n" + "="*60)
        print("🏁 최종 결론")
        print("="*60)
        
        if basic_success:
            print("✅ LLM 기반 분석기가 키워드 방식을 성공적으로 대체할 수 있습니다!")
            print("🚀 견고하고 확장 가능한 서비스 선택 로직이 구현되었습니다.")
            print("\n📈 장점:")
            print("  • 자연스러운 사용자 표현 처리")
            print("  • 높은 정확도와 신뢰도")
            print("  • 불분명한 입력에 대한 적절한 처리")
            print("  • 확장성과 유지보수성")
        else:
            print("⚠️ 추가 개선이 필요합니다.")
            print("💡 프롬프트 튜닝이나 예시 확장을 고려해보세요.")
    
    asyncio.run(main())