#!/usr/bin/env python3
"""
업무 프로세스 완료 테스트

이 테스트는 에이전트가 고객의 업무 목적을 파악하고 해당 업무를 
시나리오에 따라 완료할 수 있는지 평가합니다.
"""

import asyncio
import json
import datetime
from pathlib import Path
from typing import List, Dict, Any
import os
import sys

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from app.graph.agent import main_agent_router_node, call_scenario_agent_node, process_scenario_logic_node
from app.services.rag_service import rag_service


class BusinessProcessTester:
    """업무 프로세스 완료를 테스트하는 클래스"""
    
    def __init__(self):
        self.test_cases = self._load_business_scenarios()
        self.results = []
        
    def _load_business_scenarios(self) -> List[Dict[str, Any]]:
        """업무 목적별 테스트 시나리오"""
        return [
            {
                "business_name": "디딤돌대출_신청상담",
                "customer_intent": "대출 신청 상담을 받고 싶음",
                "conversation_flow": [
                    {
                        "turn": 1,
                        "user_input": "디딤돌 대출 신청하고 싶어요",
                        "expected_action": "set_product_type_didimdol",
                        "expected_scenario_trigger": True,
                        "expected_stage": "greeting"
                    },
                    {
                        "turn": 2,
                        "user_input": "네, 상담 시작해주세요",
                        "expected_stage": "ask_loan_purpose",
                        "expected_info_collection": True
                    },
                    {
                        "turn": 3,
                        "user_input": "집 사려고 해요",
                        "expected_stage": "check_eligibility",
                        "expected_collected_info": {"loan_purpose": "home_purchase"}
                    }
                ],
                "success_criteria": {
                    "scenario_started": True,
                    "info_collected": ["loan_purpose"],
                    "min_stages_completed": 2,
                    "process_completion_rate": 0.6  # 60% 이상 진행
                }
            },
            {
                "business_name": "전세자금대출_급한신청",
                "customer_intent": "전세 계약이 급한 상황에서 대출 신청",
                "conversation_flow": [
                    {
                        "turn": 1,
                        "user_input": "다음 주에 전세 계약해야 하는데 전세자금대출 신청하고 싶어요",
                        "expected_action": "set_product_type_jeonse",
                        "expected_scenario_trigger": True,
                        "expected_stage": "greeting"
                    },
                    {
                        "turn": 2,
                        "user_input": "네, 급해서 빨리 진행하고 싶어요",
                        "expected_stage": "check_urgency",
                        "expected_info_collection": True
                    }
                ],
                "success_criteria": {
                    "scenario_started": True,
                    "urgency_recognized": True,
                    "fast_track_offered": True
                }
            },
            {
                "business_name": "계좌개설_목적",
                "customer_intent": "새 계좌 개설",
                "conversation_flow": [
                    {
                        "turn": 1,
                        "user_input": "계좌 개설하고 싶어요",
                        "expected_action": "set_product_type_deposit_account",
                        "expected_scenario_trigger": True
                    },
                    {
                        "turn": 2,
                        "user_input": "급여통장으로 쓰려고 해요",
                        "expected_info_collection": True,
                        "expected_collected_info": {"account_purpose": "salary"}
                    }
                ],
                "success_criteria": {
                    "scenario_started": True,
                    "account_type_determined": True,
                    "required_documents_provided": True
                }
            },
            {
                "business_name": "복합_업무_처리",
                "customer_intent": "대출 상담 후 계좌 개설까지",
                "conversation_flow": [
                    {
                        "turn": 1,
                        "user_input": "디딤돌 대출 받고 나서 새 계좌도 만들고 싶어요",
                        "expected_action": "set_product_type_didimdol",
                        "expected_scenario_trigger": True,
                        "note": "복합 업무 중 첫 번째 업무 먼저 처리"
                    },
                    {
                        "turn": 2,
                        "user_input": "네, 대출 먼저 상담받을게요",
                        "expected_stage": "ask_loan_purpose"
                    },
                    {
                        "turn": 3,
                        "user_input": "대출 상담은 끝났고, 이제 계좌 개설 상담받고 싶어요",
                        "expected_action": "set_product_type_deposit_account",
                        "expected_context_switch": True
                    }
                ],
                "success_criteria": {
                    "multiple_scenarios_handled": True,
                    "context_switching": True,
                    "sequential_process_completion": True
                }
            },
            {
                "business_name": "문의만_하는_고객",
                "customer_intent": "단순 정보 문의 (업무 진행 의사 없음)",
                "conversation_flow": [
                    {
                        "turn": 1,
                        "user_input": "디딤돌 대출이 뭔가요?",
                        "expected_action": "invoke_qa_agent",
                        "expected_scenario_trigger": False,
                        "note": "정보 문의만 하는 경우"
                    },
                    {
                        "turn": 2,
                        "user_input": "그냥 궁금해서 물어본 거예요. 감사해요",
                        "expected_action": "answer_directly_chit_chat",
                        "expected_scenario_trigger": False
                    }
                ],
                "success_criteria": {
                    "information_provided": True,
                    "no_unnecessary_scenario_trigger": True,
                    "appropriate_qa_response": True
                }
            }
        ]
    
    async def test_single_scenario(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """단일 업무 시나리오 테스트"""
        print(f"\n🎯 테스트: {scenario['business_name']}")
        print(f"   고객 의도: {scenario['customer_intent']}")
        
        conversation_state = {
            "session_id": f"test_{datetime.datetime.now().strftime('%H%M%S')}",
            "messages": [],
            "available_product_types": ["didimdol", "jeonse", "deposit_account"],
            "current_product_type": None,
            "current_scenario_stage_id": None,
            "collected_product_info": {},
            "active_scenario_name": "Not Selected"
        }
        
        scenario_results = {
            "scenario_name": scenario["business_name"],
            "success": False,
            "turns_completed": 0,
            "actions_taken": [],
            "stages_visited": [],
            "info_collected": {},
            "scenario_triggered": False,
            "issues": []
        }
        
        try:
            for turn_data in scenario["conversation_flow"]:
                turn_num = turn_data["turn"]
                user_input = turn_data["user_input"]
                
                print(f"\n   턴 {turn_num}: '{user_input}'")
                
                # 사용자 메시지 추가
                conversation_state["messages"].append(HumanMessage(content=user_input))
                conversation_state["user_input_text"] = user_input
                conversation_state["stt_result"] = user_input
                
                # 메인 에이전트 라우터 실행
                result = await main_agent_router_node(conversation_state)
                conversation_state.update(result)
                
                # 결과 분석
                action_plan = result.get("action_plan", [])
                current_action = action_plan[0] if action_plan else None
                scenario_results["actions_taken"].append(current_action)
                
                print(f"      실행된 액션: {current_action}")
                
                # 시나리오 실행 여부 확인
                if current_action and "scenario" in current_action:
                    scenario_results["scenario_triggered"] = True
                    print(f"      ✅ 시나리오 트리거됨")
                    
                    # 시나리오 로직 실행 시뮬레이션
                    if conversation_state.get("current_product_type"):
                        try:
                            scenario_result = await call_scenario_agent_node(conversation_state)
                            conversation_state.update(scenario_result)
                            
                            process_result = await process_scenario_logic_node(conversation_state)
                            conversation_state.update(process_result)
                            
                            current_stage = conversation_state.get("current_scenario_stage_id")
                            scenario_results["stages_visited"].append(current_stage)
                            print(f"      현재 스테이지: {current_stage}")
                            
                        except Exception as e:
                            print(f"      ⚠️ 시나리오 실행 오류: {e}")
                            scenario_results["issues"].append(f"시나리오 실행 오류: {e}")
                
                # 예상 결과와 비교
                expected_action = turn_data.get("expected_action")
                if expected_action and current_action != expected_action:
                    issue = f"턴 {turn_num}: 예상 액션 '{expected_action}' != 실제 '{current_action}'"
                    scenario_results["issues"].append(issue)
                    print(f"      ❌ {issue}")
                else:
                    print(f"      ✅ 예상 액션 일치")
                
                scenario_results["turns_completed"] = turn_num
                scenario_results["info_collected"] = conversation_state.get("collected_product_info", {})
            
            # 성공 기준 평가
            success_criteria = scenario["success_criteria"]
            success_score = 0
            total_criteria = len(success_criteria)
            
            for criterion, expected_value in success_criteria.items():
                if criterion == "scenario_started":
                    if scenario_results["scenario_triggered"] == expected_value:
                        success_score += 1
                elif criterion == "info_collected":
                    collected_keys = set(scenario_results["info_collected"].keys())
                    expected_keys = set(expected_value)
                    if collected_keys.issuperset(expected_keys):
                        success_score += 1
                elif criterion == "min_stages_completed":
                    if len(scenario_results["stages_visited"]) >= expected_value:
                        success_score += 1
                elif criterion == "process_completion_rate":
                    completion_rate = scenario_results["turns_completed"] / len(scenario["conversation_flow"])
                    if completion_rate >= expected_value:
                        success_score += 1
            
            scenario_results["success_rate"] = success_score / total_criteria
            scenario_results["success"] = scenario_results["success_rate"] >= 0.7
            
            print(f"   📊 성공률: {scenario_results['success_rate']:.1%}")
            
        except Exception as e:
            print(f"   ❌ 테스트 실행 오류: {e}")
            scenario_results["issues"].append(f"테스트 실행 오류: {e}")
        
        return scenario_results
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """모든 업무 프로세스 테스트 실행"""
        print("🏢 업무 프로세스 완료 테스트 시작")
        print("=" * 80)
        
        all_results = []
        
        for scenario in self.test_cases:
            result = await self.test_single_scenario(scenario)
            all_results.append(result)
            self.results.append(result)
        
        # 전체 결과 분석
        total_scenarios = len(all_results)
        successful_scenarios = sum(1 for r in all_results if r["success"])
        
        summary = {
            "total_scenarios": total_scenarios,
            "successful_scenarios": successful_scenarios,
            "success_rate": successful_scenarios / total_scenarios if total_scenarios > 0 else 0,
            "detailed_results": all_results,
            "analysis": self._analyze_results(all_results)
        }
        
        return summary
    
    def _analyze_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """결과 분석"""
        analysis = {
            "common_issues": [],
            "scenario_trigger_rate": 0,
            "info_collection_rate": 0,
            "stage_progression_rate": 0,
            "recommendations": []
        }
        
        # 시나리오 트리거 성공률
        trigger_success = sum(1 for r in results if r["scenario_triggered"])
        analysis["scenario_trigger_rate"] = trigger_success / len(results)
        
        # 정보 수집 성공률
        info_success = sum(1 for r in results if r["info_collected"])
        analysis["info_collection_rate"] = info_success / len(results)
        
        # 스테이지 진행 성공률
        stage_success = sum(1 for r in results if r["stages_visited"])
        analysis["stage_progression_rate"] = stage_success / len(results)
        
        # 공통 이슈 분석
        all_issues = []
        for result in results:
            all_issues.extend(result["issues"])
        
        from collections import Counter
        issue_counts = Counter(all_issues)
        analysis["common_issues"] = issue_counts.most_common(5)
        
        # 개선 권장사항
        if analysis["scenario_trigger_rate"] < 0.8:
            analysis["recommendations"].append("업무 의도 파악 및 시나리오 트리거링 개선 필요")
        
        if analysis["info_collection_rate"] < 0.7:
            analysis["recommendations"].append("고객 정보 수집 프로세스 개선 필요")
        
        if analysis["stage_progression_rate"] < 0.6:
            analysis["recommendations"].append("시나리오 스테이지 진행 로직 개선 필요")
        
        return analysis


async def main():
    """메인 실행 함수"""
    print("🏢 디딤돌 음성 에이전트 - 업무 프로세스 완료 테스트")
    print("=" * 80)
    
    tester = BusinessProcessTester()
    
    try:
        # RAG 서비스 초기화
        print("🔧 서비스 초기화 중...")
        if hasattr(rag_service, 'initialize'):
            await rag_service.initialize()
        
        # 테스트 실행
        results = await tester.run_all_tests()
        
        # 결과 출력
        print("\n" + "=" * 80)
        print("📊 업무 프로세스 테스트 결과")
        print("=" * 80)
        
        print(f"전체 시나리오: {results['total_scenarios']}개")
        print(f"성공 시나리오: {results['successful_scenarios']}개")
        print(f"전체 성공률: {results['success_rate']:.1%}")
        
        analysis = results["analysis"]
        print(f"\n📈 세부 분석:")
        print(f"  시나리오 트리거 성공률: {analysis['scenario_trigger_rate']:.1%}")
        print(f"  정보 수집 성공률: {analysis['info_collection_rate']:.1%}")
        print(f"  스테이지 진행 성공률: {analysis['stage_progression_rate']:.1%}")
        
        print(f"\n🚨 주요 이슈:")
        for issue, count in analysis["common_issues"]:
            print(f"  - {issue} ({count}회)")
        
        print(f"\n💡 개선 권장사항:")
        for recommendation in analysis["recommendations"]:
            print(f"  - {recommendation}")
        
        # 시나리오별 상세 결과
        print(f"\n📋 시나리오별 상세 결과:")
        for result in results["detailed_results"]:
            status = "✅ 성공" if result["success"] else "❌ 실패"
            print(f"\n  {status} {result['scenario_name']}")
            print(f"     성공률: {result['success_rate']:.1%}")
            print(f"     완료 턴: {result['turns_completed']}")
            print(f"     시나리오 트리거: {'Yes' if result['scenario_triggered'] else 'No'}")
            print(f"     수집된 정보: {result['info_collected']}")
            if result["issues"]:
                print(f"     이슈: {'; '.join(result['issues'][:2])}")
        
        # 결과 저장
        results_file = Path("business_process_test_results.json")
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