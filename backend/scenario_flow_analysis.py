#!/usr/bin/env python3
"""
시나리오 흐름 분석 및 테스트 스크립트

이 스크립트는 시나리오 시작 로직과 자연스러운 전환을 분석하고
각 업무 유형별로 시나리오가 올바르게 트리거되는지 테스트합니다.
"""

import asyncio
import json
import datetime
from pathlib import Path
from typing import List, Dict, Any
import sys

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from app.graph.agent import run_agent_streaming
from app.services.rag_service import rag_service


class ScenarioFlowAnalyzer:
    """시나리오 흐름 분석 클래스"""
    
    def __init__(self):
        self.analysis_results = []
        
    def _load_scenario_trigger_test_cases(self) -> List[Dict[str, Any]]:
        """시나리오 트리거 테스트 케이스 로드"""
        return [
            {
                "test_name": "디딤돌_직접_신청",
                "customer_intent": "디딤돌 대출을 직접 신청하려는 고객",
                "input_sequence": [
                    {
                        "turn": 1,
                        "user_input": "디딤돌 대출 신청하고 싶어요",
                        "expected_flow": {
                            "should_trigger_scenario": True,
                            "expected_product_type": "didimdol",
                            "expected_scenario_name": "신한은행 디딤돌 주택담보대출 상담",
                            "expected_initial_stage": "greeting",
                            "expected_response_contains": ["상담 서비스입니다", "상담을 시작하시겠습니까"]
                        }
                    },
                    {
                        "turn": 2,
                        "user_input": "네, 시작해주세요",
                        "expected_flow": {
                            "should_continue_scenario": True,
                            "expected_next_stage": "ask_loan_purpose",
                            "expected_response_contains": ["주택 구입", "목적"]
                        }
                    }
                ]
            },
            {
                "test_name": "전세자금_급한상황",
                "customer_intent": "긴급하게 전세자금 대출이 필요한 고객",
                "input_sequence": [
                    {
                        "turn": 1,
                        "user_input": "다음 주에 전세 계약해야 하는데 전세자금대출 신청하고 싶어요",
                        "expected_flow": {
                            "should_trigger_scenario": True,
                            "expected_product_type": "jeonse",
                            "expected_scenario_name": "신한은행 전세자금대출 상담",
                            "expected_initial_stage": "greeting_jeonse",
                            "urgency_keywords": ["다음 주", "급"]
                        }
                    },
                    {
                        "turn": 2,
                        "user_input": "자격조건 알려주세요",
                        "expected_flow": {
                            "should_continue_scenario": True,
                            "expected_next_stage": "ask_marital_status_jeonse",
                            "expected_response_contains": ["혼인 상태", "미혼", "기혼"]
                        }
                    }
                ]
            },
            {
                "test_name": "계좌개설_직접요청",
                "customer_intent": "입출금통장 개설을 원하는 고객",
                "input_sequence": [
                    {
                        "turn": 1,
                        "user_input": "계좌 개설하고 싶어요",
                        "expected_flow": {
                            "should_trigger_scenario": True,
                            "expected_product_type": "deposit_account",
                            "expected_scenario_name": "신한은행 입출금통장 신규 상담",
                            "expected_initial_stage": "greeting_deposit"
                        }
                    },
                    {
                        "turn": 2,
                        "user_input": "체크카드도 같이 만들고 싶어요",
                        "expected_flow": {
                            "should_continue_scenario": True,
                            "expected_info_collection": {"additional_services_choice": "체크카드"},
                            "expected_next_stage": "ask_lifelong_account"
                        }
                    }
                ]
            },
            {
                "test_name": "모호한_대출문의",
                "customer_intent": "구체적이지 않은 대출 문의",
                "input_sequence": [
                    {
                        "turn": 1,
                        "user_input": "대출 받고 싶어요",
                        "expected_flow": {
                            "should_trigger_scenario": False,
                            "should_clarify": True,
                            "expected_action": "clarify_product_type",
                            "expected_response_contains": ["어떤 대출", "종류"]
                        }
                    },
                    {
                        "turn": 2,
                        "user_input": "주택 사려고 하는데요",
                        "expected_flow": {
                            "should_trigger_scenario": True,
                            "expected_product_type": "didimdol",
                            "expected_scenario_name": "신한은행 디딤돌 주택담보대출 상담"
                        }
                    }
                ]
            },
            {
                "test_name": "단순_정보문의",
                "customer_intent": "신청 의도 없이 정보만 궁금한 고객",
                "input_sequence": [
                    {
                        "turn": 1,
                        "user_input": "디딤돌 대출이 뭔가요?",
                        "expected_flow": {
                            "should_trigger_scenario": False,
                            "expected_action": "invoke_qa_agent",
                            "expected_response_contains": ["디딤돌 대출", "정보"]
                        }
                    },
                    {
                        "turn": 2,
                        "user_input": "그냥 궁금해서 물어본 거예요. 감사해요",
                        "expected_flow": {
                            "should_trigger_scenario": False,
                            "expected_action": "answer_directly_chit_chat",
                            "conversation_should_end": True
                        }
                    }
                ]
            }
        ]
    
    async def test_scenario_trigger_flow(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """단일 시나리오 트리거 흐름 테스트"""
        
        print(f"\n🎯 테스트: {test_case['test_name']}")
        print(f"   고객 의도: {test_case['customer_intent']}")
        
        test_result = {
            "test_name": test_case["test_name"],
            "customer_intent": test_case["customer_intent"],
            "turns_tested": 0,
            "turns_passed": 0,
            "scenario_triggered": False,
            "product_type_set": None,
            "scenario_name": None,
            "turn_results": [],
            "overall_success": False,
            "issues": []
        }
        
        # 대화 상태 초기화
        current_state = None
        session_id = f"test_{test_case['test_name']}_{datetime.datetime.now().strftime('%H%M%S')}"
        
        try:
            for turn_data in test_case["input_sequence"]:
                turn_num = turn_data["turn"]
                user_input = turn_data["user_input"]
                expected_flow = turn_data["expected_flow"]
                
                print(f"\n   턴 {turn_num}: '{user_input}'")
                
                # 에이전트 실행
                final_state = None
                async for chunk in run_agent_streaming(
                    user_input_text=user_input,
                    session_id=session_id,
                    current_state_dict=current_state
                ):
                    if chunk.get("type") == "final_state":
                        final_state = chunk.get("data")
                        break
                
                if not final_state:
                    test_result["issues"].append(f"턴 {turn_num}: 에이전트 응답 실패")
                    continue
                
                # 현재 상태 업데이트
                current_state = final_state
                
                # 턴별 결과 분석
                turn_result = await self._analyze_turn_result(
                    turn_num, user_input, final_state, expected_flow
                )
                
                test_result["turn_results"].append(turn_result)
                test_result["turns_tested"] += 1
                
                if turn_result["passed"]:
                    test_result["turns_passed"] += 1
                
                # 시나리오 트리거 확인
                if final_state.get("current_product_type"):
                    test_result["scenario_triggered"] = True
                    test_result["product_type_set"] = final_state.get("current_product_type")
                    test_result["scenario_name"] = final_state.get("active_scenario_name")
                
                print(f"      응답: {final_state.get('final_response_text_for_tts', '')[:100]}...")
                print(f"      결과: {'✅ 통과' if turn_result['passed'] else '❌ 실패'}")
                
                if turn_result["issues"]:
                    for issue in turn_result["issues"]:
                        print(f"      이슈: {issue}")
                        test_result["issues"].append(f"턴 {turn_num}: {issue}")
            
            # 전체 성공률 계산
            if test_result["turns_tested"] > 0:
                success_rate = test_result["turns_passed"] / test_result["turns_tested"]
                test_result["overall_success"] = success_rate >= 0.8
            
            print(f"   📊 결과: {test_result['turns_passed']}/{test_result['turns_tested']} 통과")
            
        except Exception as e:
            print(f"   ❌ 테스트 실행 오류: {e}")
            test_result["issues"].append(f"테스트 실행 오류: {e}")
        
        return test_result
    
    async def _analyze_turn_result(self, turn_num: int, user_input: str, 
                                 final_state: Dict[str, Any], expected_flow: Dict[str, Any]) -> Dict[str, Any]:
        """턴별 결과 분석"""
        
        turn_result = {
            "turn": turn_num,
            "user_input": user_input,
            "passed": True,
            "checks_performed": [],
            "issues": []
        }
        
        response_text = final_state.get("final_response_text_for_tts", "")
        
        # 시나리오 트리거 확인
        if expected_flow.get("should_trigger_scenario"):
            if final_state.get("current_product_type") == expected_flow.get("expected_product_type"):
                turn_result["checks_performed"].append("✅ 올바른 제품 유형 설정")
            else:
                turn_result["passed"] = False
                turn_result["issues"].append(f"제품 유형 불일치: 예상={expected_flow.get('expected_product_type')}, 실제={final_state.get('current_product_type')}")
        
        # 시나리오 이름 확인
        if expected_flow.get("expected_scenario_name"):
            if final_state.get("active_scenario_name") == expected_flow.get("expected_scenario_name"):
                turn_result["checks_performed"].append("✅ 올바른 시나리오 로드")
            else:
                turn_result["passed"] = False
                turn_result["issues"].append(f"시나리오 이름 불일치: 예상={expected_flow.get('expected_scenario_name')}, 실제={final_state.get('active_scenario_name')}")
        
        # 응답 내용 확인
        if expected_flow.get("expected_response_contains"):
            for keyword in expected_flow["expected_response_contains"]:
                if keyword in response_text:
                    turn_result["checks_performed"].append(f"✅ 키워드 '{keyword}' 포함")
                else:
                    turn_result["passed"] = False
                    turn_result["issues"].append(f"키워드 '{keyword}' 누락")
        
        # 정보 수집 확인
        if expected_flow.get("expected_info_collection"):
            collected_info = final_state.get("collected_product_info", {})
            for key, expected_value in expected_flow["expected_info_collection"].items():
                if key in collected_info:
                    turn_result["checks_performed"].append(f"✅ 정보 수집: {key}")
                else:
                    turn_result["passed"] = False
                    turn_result["issues"].append(f"정보 수집 실패: {key}")
        
        return turn_result
    
    async def run_all_scenario_trigger_tests(self) -> Dict[str, Any]:
        """모든 시나리오 트리거 테스트 실행"""
        
        print("🏢 시나리오 트리거 및 흐름 분석 테스트 시작")
        print("=" * 80)
        
        test_cases = self._load_scenario_trigger_test_cases()
        all_results = []
        
        for test_case in test_cases:
            result = await self.test_scenario_trigger_flow(test_case)
            all_results.append(result)
            self.analysis_results.append(result)
        
        # 전체 결과 분석
        total_tests = len(all_results)
        successful_tests = sum(1 for r in all_results if r["overall_success"])
        
        summary = {
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": successful_tests / total_tests if total_tests > 0 else 0,
            "detailed_results": all_results,
            "flow_analysis": self._analyze_scenario_flows(all_results)
        }
        
        return summary
    
    def _analyze_scenario_flows(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """시나리오 흐름 분석"""
        
        analysis = {
            "scenario_trigger_success_rate": 0,
            "natural_flow_rate": 0,
            "common_trigger_issues": [],
            "product_type_accuracy": {},
            "recommendations": []
        }
        
        # 시나리오 트리거 성공률
        triggered_count = sum(1 for r in results if r["scenario_triggered"])
        analysis["scenario_trigger_success_rate"] = triggered_count / len(results)
        
        # 자연스러운 흐름률 (2턴 이상 성공적으로 진행된 케이스)
        natural_flow_count = sum(1 for r in results if r["turns_passed"] >= 2)
        analysis["natural_flow_rate"] = natural_flow_count / len(results)
        
        # 제품 유형별 정확도
        for result in results:
            product_type = result.get("product_type_set")
            if product_type:
                if product_type not in analysis["product_type_accuracy"]:
                    analysis["product_type_accuracy"][product_type] = {"total": 0, "success": 0}
                analysis["product_type_accuracy"][product_type]["total"] += 1
                if result["overall_success"]:
                    analysis["product_type_accuracy"][product_type]["success"] += 1
        
        # 공통 이슈 분석
        all_issues = []
        for result in results:
            all_issues.extend(result["issues"])
        
        from collections import Counter
        issue_counts = Counter(all_issues)
        analysis["common_trigger_issues"] = issue_counts.most_common(5)
        
        # 개선 권장사항
        if analysis["scenario_trigger_success_rate"] < 0.8:
            analysis["recommendations"].append("시나리오 트리거 로직 개선 필요")
        
        if analysis["natural_flow_rate"] < 0.7:
            analysis["recommendations"].append("자연스러운 대화 흐름 개선 필요")
        
        return analysis


async def main():
    """메인 실행 함수"""
    print("🏢 디딤돌 음성 에이전트 - 시나리오 흐름 분석")
    print("=" * 80)
    
    analyzer = ScenarioFlowAnalyzer()
    
    try:
        # RAG 서비스 초기화
        print("🔧 서비스 초기화 중...")
        if hasattr(rag_service, 'initialize'):
            await rag_service.initialize()
        
        # 시나리오 트리거 테스트 실행
        results = await analyzer.run_all_scenario_trigger_tests()
        
        # 결과 출력
        print("\n" + "=" * 80)
        print("📊 시나리오 흐름 분석 결과")
        print("=" * 80)
        
        print(f"전체 테스트: {results['total_tests']}개")
        print(f"성공 테스트: {results['successful_tests']}개")
        print(f"전체 성공률: {results['success_rate']:.1%}")
        
        flow_analysis = results["flow_analysis"]
        print(f"\n📈 흐름 분석:")
        print(f"  시나리오 트리거 성공률: {flow_analysis['scenario_trigger_success_rate']:.1%}")
        print(f"  자연스러운 흐름률: {flow_analysis['natural_flow_rate']:.1%}")
        
        print(f"\n🎯 제품별 정확도:")
        for product_type, stats in flow_analysis["product_type_accuracy"].items():
            accuracy = stats["success"] / stats["total"] if stats["total"] > 0 else 0
            print(f"  {product_type}: {accuracy:.1%} ({stats['success']}/{stats['total']})")
        
        print(f"\n🚨 주요 이슈:")
        for issue, count in flow_analysis["common_trigger_issues"]:
            print(f"  - {issue} ({count}회)")
        
        print(f"\n💡 개선 권장사항:")
        for recommendation in flow_analysis["recommendations"]:
            print(f"  - {recommendation}")
        
        # 결과 저장
        results_file = Path("scenario_flow_analysis_results.json")
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n💾 결과 저장: {results_file}")
        
        return results
        
    except Exception as e:
        print(f"❌ 테스트 실행 중 오류: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    asyncio.run(main())