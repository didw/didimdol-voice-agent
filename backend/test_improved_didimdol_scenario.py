#!/usr/bin/env python3
"""
개선된 디딤돌 대출 시나리오 테스트

다중 정보 수집과 자연스러운 대화 흐름을 테스트합니다.
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


class ImprovedDidimdolScenarioTester:
    """개선된 디딤돌 대출 시나리오 테스터"""
    
    def __init__(self):
        self.test_cases = self._load_test_cases()
        self.results = []
        
    def _load_test_cases(self) -> List[Dict[str, Any]]:
        """개선된 시나리오 테스트 케이스"""
        return [
            {
                "test_name": "다중_정보_한번에_제공",
                "description": "고객이 필요한 정보를 한번에 제공하는 경우",
                "conversation_flow": [
                    {
                        "turn": 1,
                        "user_input": "디딤돌 대출 신청하고 싶어요",
                        "expected_action": "set_product_type",
                        "expected_stage": "info_collection_guidance"
                    },
                    {
                        "turn": 2,
                        "user_input": "주택 구입 목적이고, 미혼이고, 무주택이에요. 연소득은 5000만원 정도이고 3억원짜리 집을 사려고 해요",
                        "expected_info_extracted": {
                            "loan_purpose_confirmed": True,
                            "marital_status": "미혼",
                            "has_home": False,
                            "annual_income": 5000,
                            "target_home_price": 30000
                        },
                        "expected_stage": "eligibility_assessment"
                    },
                    {
                        "turn": 3,
                        "user_input": "네, 서류 안내받고 싶어요",
                        "expected_stage": "application_documents_guidance"
                    }
                ]
            },
            {
                "test_name": "그룹별_정보_제공",
                "description": "고객이 그룹별로 정보를 제공하는 경우 (개선된 방식)",
                "conversation_flow": [
                    {
                        "turn": 1,
                        "user_input": "디딤돌 대출 신청하고 싶어요",
                        "expected_action": "set_product_type",
                        "expected_stage": "info_collection_guidance"
                    },
                    {
                        "turn": 2,
                        "user_input": "연소득만 알려드릴게요. 6000만원입니다",
                        "expected_info_extracted": {"annual_income": 6000},
                        "expected_stage": "ask_missing_info_group1"
                    },
                    {
                        "turn": 3,
                        "user_input": "주택 구입 목적이고 기혼입니다",
                        "expected_info_extracted": {"loan_purpose_confirmed": True, "marital_status": "기혼"},
                        "expected_stage": "ask_missing_info_group2"
                    },
                    {
                        "turn": 4,
                        "user_input": "무주택이에요",
                        "expected_info_extracted": {"has_home": False},
                        "expected_stage": "ask_missing_info_group3"
                    },
                    {
                        "turn": 5,
                        "user_input": "4억원 정도 집을 생각하고 있어요",
                        "expected_info_extracted": {"target_home_price": 40000},
                        "expected_stage": "eligibility_assessment"
                    }
                ]
            },
            {
                "test_name": "부분_정보_제공_후_그룹별_보완",
                "description": "일부 정보만 제공하고 나머지는 그룹별로 요청받아 제공하는 경우",
                "conversation_flow": [
                    {
                        "turn": 1,
                        "user_input": "디딤돌 대출 신청하고 싶어요",
                        "expected_action": "set_product_type",
                        "expected_stage": "info_collection_guidance"
                    },
                    {
                        "turn": 2,
                        "user_input": "주택 구입 목적이고 예비부부입니다",
                        "expected_info_extracted": {
                            "loan_purpose_confirmed": True,
                            "marital_status": "예비부부"
                        },
                        "expected_stage": "ask_missing_info_group2"
                    },
                    {
                        "turn": 3,
                        "user_input": "무주택이고 연소득은 7000만원입니다",
                        "expected_info_extracted": {
                            "has_home": False,
                            "annual_income": 7000
                        },
                        "expected_stage": "ask_missing_info_group3"
                    },
                    {
                        "turn": 4,
                        "user_input": "집값은 4억 정도 생각하고 있어요",
                        "expected_info_extracted": {
                            "target_home_price": 40000
                        },
                        "expected_stage": "eligibility_assessment"
                    }
                ]
            }
        ]
    
    async def test_single_scenario(self, test_case: Dict[str, Any]) -> Dict[str, Any]:
        """단일 시나리오 테스트"""
        print(f"\n🎯 테스트: {test_case['test_name']}")
        print(f"   설명: {test_case['description']}")
        
        conversation_state = {
            "session_id": f"test_{datetime.datetime.now().strftime('%H%M%S')}",
            "messages": [],
            "available_product_types": ["didimdol", "jeonse", "deposit_account"],
            "current_product_type": None,
            "current_scenario_stage_id": None,
            "collected_product_info": {},
            "active_scenario_name": "Not Selected"
        }
        
        test_results = {
            "test_name": test_case["test_name"],
            "success": True,
            "turns_completed": 0,
            "stages_visited": [],
            "info_collected": {},
            "issues": [],
            "extracted_info_history": []
        }
        
        try:
            for turn_data in test_case["conversation_flow"]:
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
                current_stage = conversation_state.get("current_scenario_stage_id")
                
                print(f"      실행된 액션: {current_action}")
                print(f"      현재 스테이지: {current_stage}")
                print(f"      수집된 정보: {conversation_state.get('collected_product_info', {})}")
                
                # 예상 액션 검증
                expected_action = turn_data.get("expected_action")
                if expected_action and current_action != expected_action:
                    issue = f"턴 {turn_num}: 예상 액션 '{expected_action}' != 실제 '{current_action}'"
                    test_results["issues"].append(issue)
                    test_results["success"] = False
                    print(f"      ❌ {issue}")
                else:
                    print(f"      ✅ 액션 확인")
                
                # 예상 스테이지 검증
                expected_stage = turn_data.get("expected_stage")
                if expected_stage and current_stage != expected_stage:
                    issue = f"턴 {turn_num}: 예상 스테이지 '{expected_stage}' != 실제 '{current_stage}'"
                    test_results["issues"].append(issue)
                    test_results["success"] = False
                    print(f"      ❌ {issue}")
                else:
                    print(f"      ✅ 스테이지 확인")
                
                # 예상 정보 추출 검증
                expected_info = turn_data.get("expected_info_extracted", {})
                if expected_info:
                    collected_info = conversation_state.get("collected_product_info", {})
                    missing_info = []
                    for key, expected_value in expected_info.items():
                        if key not in collected_info or collected_info[key] != expected_value:
                            missing_info.append(f"{key}={expected_value}")
                    
                    if missing_info:
                        issue = f"턴 {turn_num}: 정보 추출 실패 - {', '.join(missing_info)}"
                        test_results["issues"].append(issue)
                        test_results["success"] = False
                        print(f"      ❌ {issue}")
                    else:
                        print(f"      ✅ 정보 추출 확인")
                
                test_results["turns_completed"] = turn_num
                test_results["info_collected"] = conversation_state.get("collected_product_info", {})
                test_results["stages_visited"].append(current_stage)
                test_results["extracted_info_history"].append({
                    "turn": turn_num,
                    "info": conversation_state.get("collected_product_info", {}).copy()
                })
                
        except Exception as e:
            print(f"   ❌ 테스트 실행 오류: {e}")
            test_results["issues"].append(f"테스트 실행 오류: {e}")
            test_results["success"] = False
        
        return test_results
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """모든 테스트 실행"""
        print("🔧 개선된 디딤돌 대출 시나리오 테스트 시작")
        print("=" * 80)
        
        all_results = []
        
        for test_case in self.test_cases:
            result = await self.test_single_scenario(test_case)
            all_results.append(result)
            self.results.append(result)
        
        # 전체 결과 분석
        total_tests = len(all_results)
        successful_tests = sum(1 for r in all_results if r["success"])
        
        summary = {
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": successful_tests / total_tests if total_tests > 0 else 0,
            "detailed_results": all_results
        }
        
        return summary


async def main():
    """메인 실행 함수"""
    print("🏢 디딤돌 음성 에이전트 - 개선된 시나리오 테스트")
    print("=" * 80)
    
    tester = ImprovedDidimdolScenarioTester()
    
    try:
        # RAG 서비스 초기화
        print("🔧 서비스 초기화 중...")
        if hasattr(rag_service, 'initialize'):
            await rag_service.initialize()
        
        # 테스트 실행
        results = await tester.run_all_tests()
        
        # 결과 출력
        print("\n" + "=" * 80)
        print("📊 개선된 시나리오 테스트 결과")
        print("=" * 80)
        
        print(f"전체 테스트: {results['total_tests']}개")
        print(f"성공 테스트: {results['successful_tests']}개")
        print(f"전체 성공률: {results['success_rate']:.1%}")
        
        # 테스트별 상세 결과
        print(f"\n📋 테스트별 상세 결과:")
        for result in results["detailed_results"]:
            status = "✅ 성공" if result["success"] else "❌ 실패"
            print(f"\n  {status} {result['test_name']}")
            print(f"     완료 턴: {result['turns_completed']}")
            print(f"     최종 수집 정보: {result['info_collected']}")
            print(f"     방문 스테이지: {' -> '.join(result['stages_visited'])}")
            if result["issues"]:
                print(f"     이슈: {'; '.join(result['issues'][:2])}")
            
            # 정보 수집 히스토리 출력
            print(f"     정보 수집 과정:")
            for info_snapshot in result["extracted_info_history"]:
                print(f"       턴 {info_snapshot['turn']}: {info_snapshot['info']}")
        
        # 결과 저장
        results_file = Path("improved_didimdol_scenario_test_results.json")
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