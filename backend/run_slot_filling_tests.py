#!/usr/bin/env python
"""
슬롯필링 확인 기능 테스트 실행 스크립트
PRD 기반 테스트 케이스 실행
"""
import subprocess
import sys


def run_tests():
    """테스트 실행"""
    print("🧪 슬롯필링 확인 기능 테스트 시작...\n")
    
    test_suites = [
        {
            "name": "기본 슬롯필링 확인 테스트",
            "module": "tests.test_slot_filling_confirmation",
            "description": "PRD 대화 흐름에 따른 기본 기능 테스트"
        },
        {
            "name": "확인 단계 로직 테스트",
            "module": "tests.test_confirmation_stage_logic", 
            "description": "확인/수정 의도 처리 및 그룹별 수집 전략"
        },
        {
            "name": "End-to-End 플로우 테스트",
            "module": "tests.test_e2e_slot_filling_flow",
            "description": "전체 대화 흐름 통합 테스트"
        },
        {
            "name": "기존 시나리오 통합 테스트",
            "module": "tests.test_scenario_flow_integration",
            "description": "기존 기능과의 호환성 테스트"
        }
    ]
    
    total_tests = len(test_suites)
    passed_tests = 0
    
    for i, suite in enumerate(test_suites, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{total_tests}] {suite['name']}")
        print(f"설명: {suite['description']}")
        print(f"{'='*60}\n")
        
        try:
            # pytest 실행
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-v", "-s", f"tests/{suite['module'].split('.')[-1]}.py"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                print(f"✅ {suite['name']} - PASSED")
                passed_tests += 1
            else:
                print(f"❌ {suite['name']} - FAILED")
                print("\n오류 내용:")
                print(result.stdout)
                print(result.stderr)
        
        except Exception as e:
            print(f"❌ {suite['name']} - ERROR: {str(e)}")
    
    # 최종 결과
    print(f"\n{'='*60}")
    print(f"📊 테스트 결과: {passed_tests}/{total_tests} 통과")
    print(f"{'='*60}\n")
    
    if passed_tests == total_tests:
        print("🎉 모든 테스트가 통과했습니다!")
        return 0
    else:
        print(f"⚠️  {total_tests - passed_tests}개의 테스트가 실패했습니다.")
        return 1


if __name__ == "__main__":
    # 테스트 환경 설정 확인
    print("📋 테스트 환경 확인...")
    
    try:
        import pytest
        print("✅ pytest 설치 확인")
    except ImportError:
        print("❌ pytest가 설치되어 있지 않습니다.")
        print("설치: pip install -r requirements-test.txt")
        sys.exit(1)
    
    # 테스트 실행
    exit_code = run_tests()
    sys.exit(exit_code)