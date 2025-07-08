#!/usr/bin/env python3
"""
Phase 2: 계좌개설 라우팅 테스트

이 스크립트는 계좌개설 라우팅 개선사항을 테스트합니다.
"""

import asyncio
from pathlib import Path
import sys

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.graph.agent import run_agent_streaming
from app.services.rag_service import rag_service


async def test_account_routing():
    """계좌개설 라우팅 테스트"""
    
    print("🧪 Phase 2: 계좌개설 라우팅 테스트")
    print("=" * 60)
    
    # RAG 서비스 초기화
    print("🔧 서비스 초기화 중...")
    if hasattr(rag_service, 'initialize'):
        await rag_service.initialize()
    
    test_cases = [
        {
            "name": "계좌 개설 직접 요청",
            "input": "계좌 개설하고 싶어요",
            "expected_product": "deposit_account",
            "expected_scenario": "신한은행 입출금통장 신규 상담"
        },
        {
            "name": "통장 만들기 요청",
            "input": "통장 만들고 싶어요",
            "expected_product": "deposit_account",
            "expected_scenario": "신한은행 입출금통장 신규 상담"
        },
        {
            "name": "새 계좌 요청",
            "input": "새 계좌 필요해요",
            "expected_product": "deposit_account",
            "expected_scenario": "신한은행 입출금통장 신규 상담"
        }
    ]
    
    success_count = 0
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n🎯 테스트 {i}: {test_case['name']}")
        print(f"   입력: '{test_case['input']}'")
        
        session_id = f"test_account_{i}"
        current_state = None
        
        async for chunk in run_agent_streaming(
            user_input_text=test_case['input'],
            session_id=session_id,
            current_state_dict=current_state
        ):
            if isinstance(chunk, dict) and chunk.get("type") == "final_state":
                current_state = chunk.get("data")
                break
        
        if current_state:
            product_type = current_state.get('current_product_type')
            scenario_name = current_state.get('active_scenario_name')
            response = current_state.get('final_response_text_for_tts', '')
            
            print(f"   제품 타입: {product_type}")
            print(f"   시나리오: {scenario_name}")
            print(f"   응답: {response[:100]}...")
            
            # 검증
            success = True
            
            if product_type != test_case['expected_product']:
                print(f"   ❌ 제품 타입 불일치: 예상={test_case['expected_product']}, 실제={product_type}")
                success = False
            else:
                print(f"   ✅ 제품 타입 일치")
            
            if scenario_name != test_case['expected_scenario']:
                print(f"   ❌ 시나리오 불일치: 예상={test_case['expected_scenario']}, 실제={scenario_name}")
                success = False
            else:
                print(f"   ✅ 시나리오 일치")
            
            if "입출금통장" in response or "계좌" in response:
                print(f"   ✅ 응답 내용 적절")
            else:
                print(f"   ❌ 응답 내용 부적절")
                success = False
            
            if success:
                success_count += 1
                print(f"   🎉 테스트 {i} 성공!")
            else:
                print(f"   💥 테스트 {i} 실패")
        else:
            print(f"   ❌ 응답 받기 실패")
    
    print(f"\n📊 테스트 결과 요약")
    print("=" * 60)
    print(f"성공: {success_count}/{len(test_cases)}")
    print(f"성공률: {success_count/len(test_cases)*100:.1f}%")
    
    return success_count == len(test_cases)


async def main():
    """메인 실행 함수"""
    try:
        result = await test_account_routing()
        if result:
            print("\n🎉 Phase 2 계좌개설 라우팅 개선 성공!")
        else:
            print("\n❌ Phase 2 테스트 실패")
        return result
    except Exception as e:
        print(f"\n❌ 테스트 중 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    asyncio.run(main())