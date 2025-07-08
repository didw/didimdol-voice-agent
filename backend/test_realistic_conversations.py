#!/usr/bin/env python3
"""
실제 대화 시나리오 테스트 및 로그 분석 도구

이 스크립트는 실제 사용자 대화 패턴을 시뮬레이션하고 
대화 로그를 저장하여 에이전트의 성능을 분석합니다.
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

from langchain_core.messages import HumanMessage, AIMessage
from app.graph.agent import factual_answer_node, web_search_node
from app.services.rag_service import rag_service


class ConversationLogger:
    """대화 로그를 저장하고 분석하는 클래스"""
    
    def __init__(self, log_dir: str = "conversation_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.conversations = []
        
    def log_conversation(self, scenario: str, user_input: str, agent_response: str, 
                        metadata: Dict[str, Any] = None):
        """대화 로그 저장"""
        conversation_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "scenario": scenario,
            "user_input": user_input,
            "agent_response": agent_response,
            "metadata": metadata or {}
        }
        self.conversations.append(conversation_entry)
        
    def save_logs(self, filename: str = None):
        """로그를 JSON 파일로 저장"""
        if filename is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"conversation_log_{timestamp}.json"
            
        filepath = self.log_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.conversations, f, ensure_ascii=False, indent=2)
            
        return filepath


class RealisticConversationTester:
    """실제 대화 시나리오를 테스트하는 클래스"""
    
    def __init__(self):
        self.logger = ConversationLogger()
        self.scenarios = self._load_test_scenarios()
        
    def _load_test_scenarios(self) -> List[Dict[str, Any]]:
        """실제 대화 시나리오 로드"""
        return [
            {
                "name": "디딤돌_기본정보_문의",
                "category": "didimdol_basic",
                "conversations": [
                    {
                        "user": "안녕하세요, 디딤돌 대출에 대해 알고 싶어요",
                        "expected_topics": ["디딤돌", "청년", "대출", "주택"]
                    },
                    {
                        "user": "디딤돌 대출이 뭔가요? 처음 들어보는데요",
                        "expected_topics": ["디딤돌", "정부지원", "생애최초"]
                    }
                ]
            },
            {
                "name": "디딤돌_금리_문의",
                "category": "didimdol_interest",
                "conversations": [
                    {
                        "user": "디딤돌 대출 금리가 어떻게 되나요?",
                        "expected_topics": ["금리", "%", "연"]
                    },
                    {
                        "user": "다른 은행 대출이랑 금리 비교하면 어떤가요?",
                        "expected_topics": ["금리", "비교", "시중은행"]
                    }
                ]
            },
            {
                "name": "전세자금_급한상황",
                "category": "jeonse_urgent",
                "conversations": [
                    {
                        "user": "다음 주에 전세 계약해야 하는데 전세자금대출 받을 수 있을까요?",
                        "expected_topics": ["전세자금대출", "계약", "기간"]
                    }
                ]
            },
            {
                "name": "감정적_상황",
                "category": "emotional",
                "conversations": [
                    {
                        "user": "대출 심사에서 떨어졌어요... 너무 속상해요. 다른 방법 없을까요?",
                        "expected_topics": ["이해", "방법", "대안"]
                    }
                ]
            },
            {
                "name": "복합_문의",
                "category": "multi_product",
                "conversations": [
                    {
                        "user": "디딤돌 대출이랑 전세자금대출 둘 다 받을 수 있나요?",
                        "expected_topics": ["디딤돌", "전세자금", "중복"]
                    }
                ]
            }
        ]
    
    async def test_conversation(self, scenario: Dict[str, Any], conversation: Dict[str, Any]) -> Dict[str, Any]:
        """단일 대화 테스트"""
        user_input = conversation["user"]
        expected_topics = conversation["expected_topics"]
        
        # 에이전트 상태 설정
        state = {
            "user_input_text": user_input,
            "messages": [HumanMessage(content=user_input)],
            "stt_result": user_input,
            "action_plan": ["invoke_qa_agent"],
            "action_plan_struct": [{"tool": "invoke_qa_agent"}]
        }
        
        try:
            # RAG 서비스 준비 확인
            if not rag_service.is_ready():
                print("Warning: RAG service not ready, using fallback response")
                response = "죄송합니다. 현재 시스템 점검 중입니다."
                response_time = 0
            else:
                # 실제 에이전트 호출
                start_time = asyncio.get_event_loop().time()
                result = await factual_answer_node(state)
                end_time = asyncio.get_event_loop().time()
                response_time = end_time - start_time
                response = result.get("factual_response", "응답을 생성할 수 없습니다.")
            
            # 응답 품질 분석
            quality_analysis = self._analyze_response_quality(response, expected_topics, user_input)
            
            # 로그 저장
            metadata = {
                "response_time": response_time,
                "quality_analysis": quality_analysis,
                "expected_topics": expected_topics,
                "scenario_category": scenario["category"]
            }
            
            self.logger.log_conversation(
                scenario["name"], 
                user_input, 
                response, 
                metadata
            )
            
            return {
                "success": True,
                "user_input": user_input,
                "agent_response": response,
                "response_time": response_time,
                "quality_analysis": quality_analysis
            }
            
        except Exception as e:
            error_response = f"오류 발생: {str(e)}"
            self.logger.log_conversation(
                scenario["name"], 
                user_input, 
                error_response, 
                {"error": str(e), "scenario_category": scenario["category"]}
            )
            
            return {
                "success": False,
                "user_input": user_input,
                "agent_response": error_response,
                "error": str(e)
            }
    
    def _analyze_response_quality(self, response: str, expected_topics: List[str], user_input: str) -> Dict[str, Any]:
        """응답 품질 분석"""
        analysis = {
            "length": len(response),
            "politeness_score": 0,
            "topic_coverage": 0,
            "completeness_score": 0,
            "found_topics": [],
            "polite_markers": []
        }
        
        # 정중함 체크
        polite_markers = ['습니다', '합니다', '됩니다', '입니다', '세요', '십니다', 
                         '요', '해요', '드려요', '드립니다', '해드려요']
        found_polite = [marker for marker in polite_markers if marker in response]
        analysis["polite_markers"] = found_polite
        analysis["politeness_score"] = 1 if found_polite else 0
        
        # 주제 커버리지 체크
        found_topics = [topic for topic in expected_topics if topic in response]
        analysis["found_topics"] = found_topics
        analysis["topic_coverage"] = len(found_topics) / len(expected_topics) if expected_topics else 0
        
        # 완전성 점수 (길이와 내용 기반)
        if len(response) >= 30 and analysis["politeness_score"] > 0:
            analysis["completeness_score"] = 0.8 + (analysis["topic_coverage"] * 0.2)
        else:
            analysis["completeness_score"] = 0.3
            
        return analysis
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """모든 시나리오 테스트 실행"""
        print("🎯 실제 대화 시나리오 테스트 시작...")
        print(f"📋 총 {len(self.scenarios)}개 시나리오, {sum(len(s['conversations']) for s in self.scenarios)}개 대화 테스트")
        print("-" * 80)
        
        all_results = []
        total_conversations = 0
        successful_conversations = 0
        
        for scenario in self.scenarios:
            print(f"\n🔄 시나리오: {scenario['name']}")
            scenario_results = []
            
            for i, conversation in enumerate(scenario["conversations"], 1):
                print(f"  💬 대화 {i}: {conversation['user'][:50]}...")
                
                result = await self.test_conversation(scenario, conversation)
                scenario_results.append(result)
                total_conversations += 1
                
                if result["success"]:
                    successful_conversations += 1
                    quality = result["quality_analysis"]
                    print(f"     ✅ 성공 (응답시간: {result['response_time']:.2f}s)")
                    print(f"     📊 품질: 정중함 {quality['politeness_score']}, 주제커버리지 {quality['topic_coverage']:.1%}")
                else:
                    print(f"     ❌ 실패: {result['error']}")
                
                # 응답 출력 (처음 100자)
                response_preview = result["agent_response"][:100]
                print(f"     💭 응답: {response_preview}...")
                
            all_results.append({
                "scenario": scenario,
                "results": scenario_results
            })
        
        # 전체 결과 요약
        success_rate = successful_conversations / total_conversations if total_conversations > 0 else 0
        
        summary = {
            "total_conversations": total_conversations,
            "successful_conversations": successful_conversations,
            "success_rate": success_rate,
            "timestamp": datetime.datetime.now().isoformat(),
            "detailed_results": all_results
        }
        
        return summary


async def main():
    """메인 실행 함수"""
    print("🏠 디딤돌 음성 에이전트 - 실제 대화 시나리오 테스트")
    print("=" * 80)
    
    # 환경 변수 확인
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  Warning: OPENAI_API_KEY가 설정되지 않음")
    
    tester = RealisticConversationTester()
    
    try:
        # RAG 서비스 초기화 시도
        print("🔧 RAG 서비스 초기화 중...")
        if hasattr(rag_service, 'initialize'):
            await rag_service.initialize()
            
        # 테스트 실행
        results = await tester.run_all_tests()
        
        # 로그 저장
        log_file = tester.logger.save_logs()
        print(f"\n💾 대화 로그 저장: {log_file}")
        
        # 결과 분석 출력
        print("\n" + "=" * 80)
        print("📊 테스트 결과 분석")
        print("=" * 80)
        
        print(f"전체 대화: {results['total_conversations']}개")
        print(f"성공 대화: {results['successful_conversations']}개")
        print(f"성공률: {results['success_rate']:.1%}")
        
        # 시나리오별 분석
        print("\n📋 시나리오별 상세 분석:")
        for scenario_result in results["detailed_results"]:
            scenario_name = scenario_result["scenario"]["name"]
            scenario_results = scenario_result["results"]
            scenario_success = sum(1 for r in scenario_results if r["success"])
            scenario_total = len(scenario_results)
            
            print(f"\n  📌 {scenario_name}")
            print(f"     성공률: {scenario_success}/{scenario_total} ({scenario_success/scenario_total:.1%})")
            
            # 품질 분석
            successful_results = [r for r in scenario_results if r["success"]]
            if successful_results:
                avg_politeness = sum(r["quality_analysis"]["politeness_score"] for r in successful_results) / len(successful_results)
                avg_coverage = sum(r["quality_analysis"]["topic_coverage"] for r in successful_results) / len(successful_results)
                avg_response_time = sum(r["response_time"] for r in successful_results) / len(successful_results)
                
                print(f"     평균 정중함: {avg_politeness:.1%}")
                print(f"     평균 주제커버리지: {avg_coverage:.1%}")
                print(f"     평균 응답시간: {avg_response_time:.2f}초")
        
        # 분석 리포트 저장
        analysis_file = tester.log_dir / f"analysis_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(analysis_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n📈 분석 리포트 저장: {analysis_file}")
        
        return results
        
    except Exception as e:
        print(f"❌ 테스트 실행 중 오류: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    asyncio.run(main())