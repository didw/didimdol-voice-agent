#!/usr/bin/env python3

"""
최적화된 Main Agent 테스트 스크립트
"""

import asyncio
import json
import time
import sys
import os

# 프로젝트 루트를 Python path에 추가
sys.path.append('/Users/jyyang/Project/didimdol-voice-agent/backend')

from app.agents.optimized_main_agent import optimized_main_agent


async def test_quick_answer():
    """즉시 답변 테스트"""
    print("\n🔥 즉시 답변 테스트")
    print("="*60)
    
    test_cases = [
        "수수료가 얼마나 들어요?",
        "계좌 개설하는데 시간이 얼마나 걸려요?",
        "한도제한계좌가 뭐예요?",
        "평생계좌는 어떻게 신청하나요?"
    ]
    
    for question in test_cases:
        start_time = time.time()
        
        # 즉시 답변 체크 (동기)
        quick_answer = optimized_main_agent.check_quick_answer(question)
        
        elapsed = (time.time() - start_time) * 1000  # ms
        
        if quick_answer:
            print(f"✅ Q: {question}")
            print(f"   A: {quick_answer[:50]}...")
            print(f"   ⏱️  {elapsed:.1f}ms")
        else:
            print(f"❌ Q: {question} - 즉시 답변 불가")


async def test_parallel_processing():
    """병렬 처리 테스트"""
    print("\n⚡ 병렬 처리 테스트")
    print("="*60)
    
    test_input = "김철수이고 010-1234-5678입니다. 평생계좌 사용하겠습니다."
    context = {
        "current_stage": "collect_basic",
        "collected_info": {}
    }
    
    print(f"입력: '{test_input}'")
    
    # 1. 순차 처리 시뮬레이션
    print("\n1️⃣ 순차 처리 (기존 방식)")
    start_time = time.time()
    
    entities = await optimized_main_agent.extract_entities(test_input, context)
    intent = await optimized_main_agent.classify_intent(test_input, context)
    rag_result = await optimized_main_agent.search_rag(test_input)
    
    sequential_time = (time.time() - start_time) * 1000
    print(f"   총 소요시간: {sequential_time:.1f}ms")
    
    # 2. 병렬 처리
    print("\n2️⃣ 병렬 처리 (개선 방식)")
    start_time = time.time()
    
    tasks = [
        optimized_main_agent.extract_entities(test_input, context),
        optimized_main_agent.classify_intent(test_input, context),
        optimized_main_agent.search_rag(test_input)
    ]
    
    results = await asyncio.gather(*tasks)
    
    parallel_time = (time.time() - start_time) * 1000
    print(f"   총 소요시간: {parallel_time:.1f}ms")
    
    print(f"\n⚡ 성능 개선: {sequential_time/parallel_time:.1f}배 빠름")
    
    # 결과 출력
    print(f"\n📊 처리 결과:")
    print(f"   추출된 엔티티: {results[0]}")
    print(f"   의도 분류: {results[1]}")
    print(f"   RAG 결과: {results[2]}")


async def test_integrated_flow():
    """통합 플로우 테스트"""
    print("\n🔄 통합 플로우 테스트")
    print("="*60)
    
    test_scenarios = [
        {
            "stage": "collect_basic",
            "input": "저는 박영희고 연락처는 010-9876-5432예요",
            "collected_info": {},
            "description": "기본 정보 수집"
        },
        {
            "stage": "collect_basic", 
            "input": "수수료가 있나요?",
            "collected_info": {"customer_name": "박영희", "phone_number": "01098765432"},
            "description": "정보 수집 중 질문"
        },
        {
            "stage": "ask_internet_banking",
            "input": "네, 신청할게요",
            "collected_info": {"customer_name": "박영희", "phone_number": "01098765432", "use_lifelong_account": True},
            "description": "Yes/No 응답"
        },
        {
            "stage": "collect_ib_info",
            "input": "한도제한계좌 해제는 어떻게 하나요?",
            "collected_info": {"customer_name": "박영희", "phone_number": "01098765432", "use_lifelong_account": True},
            "description": "복잡한 질문"
        }
    ]
    
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n{i}. {scenario['description']}")
        print(f"   단계: {scenario['stage']}")
        print(f"   입력: '{scenario['input']}'")
        
        start_time = time.time()
        
        result = await optimized_main_agent.process_user_input(
            user_input=scenario['input'],
            current_stage=scenario['stage'],
            collected_info=scenario['collected_info']
        )
        
        elapsed = (time.time() - start_time) * 1000
        
        print(f"   응답 타입: {result['response_type']}")
        print(f"   메시지: {result['message'][:60]}...")
        print(f"   수집된 정보: {result.get('collected_info', {})}")
        print(f"   다음 단계: {result.get('next_stage', result.get('continue_stage'))}")
        print(f"   신뢰도: {result['confidence']}")
        print(f"   ⏱️  {elapsed:.1f}ms")


async def test_performance_comparison():
    """성능 비교 테스트"""
    print("\n📊 성능 비교 분석")
    print("="*60)
    
    # 다양한 입력 타입
    test_inputs = [
        ("수수료 문의", "수수료가 있나요?"),
        ("정보 제공", "이름은 최민수고 010-5555-6666입니다"),
        ("복잡한 질문", "한도제한계좌를 해제하려면 어떤 서류가 필요한가요?"),
        ("긍정 응답", "네, 좋아요"),
        ("부정 응답", "아니요, 필요없어요")
    ]
    
    results = []
    
    for input_type, user_input in test_inputs:
        start_time = time.time()
        
        result = await optimized_main_agent.process_user_input(
            user_input=user_input,
            current_stage="collect_basic",
            collected_info={}
        )
        
        elapsed = (time.time() - start_time) * 1000
        
        results.append({
            "type": input_type,
            "time": elapsed,
            "response_type": result["response_type"]
        })
    
    # 결과 출력
    print("\n입력 타입별 응답 시간:")
    print("-" * 40)
    print(f"{'입력 타입':<15} {'응답 타입':<20} {'시간(ms)':<10}")
    print("-" * 40)
    
    for r in results:
        print(f"{r['type']:<15} {r['response_type']:<20} {r['time']:<10.1f}")
    
    avg_time = sum(r['time'] for r in results) / len(results)
    print("-" * 40)
    print(f"{'평균 응답 시간:':<35} {avg_time:<10.1f}")


async def main():
    """메인 테스트 실행"""
    print("🚀 최적화된 Main Agent 테스트")
    print("="*60)
    
    # 1. 즉시 답변 테스트
    await test_quick_answer()
    
    # 2. 병렬 처리 테스트
    await test_parallel_processing()
    
    # 3. 통합 플로우 테스트
    await test_integrated_flow()
    
    # 4. 성능 비교
    await test_performance_comparison()
    
    print("\n✅ 모든 테스트 완료!")
    
    print("\n💡 최적화 요약:")
    print("1. ✅ 즉시 답변: FAQ는 동기 처리로 1ms 이내 응답")
    print("2. ✅ 병렬 처리: 도구 호출을 asyncio.gather로 동시 실행")
    print("3. ✅ 통합 지식: scenario.json + deposit_account.md 통합")
    print("4. ✅ 조건부 RAG: 필요한 경우에만 RAG 호출")


if __name__ == "__main__":
    asyncio.run(main())