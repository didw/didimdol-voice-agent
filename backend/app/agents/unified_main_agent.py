"""
통합 Main Agent - LLM 기반 병렬 처리 시스템
"""

import asyncio
import json
import yaml
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME


class KnowledgeManager:
    """시나리오와 매뉴얼을 통합 관리하는 지식베이스"""
    
    def __init__(self):
        self.scenario_data = self._load_scenario()
        self.manual_data = self._load_manual()
        self.unified_knowledge = self._create_unified_knowledge()
    
    def _load_scenario(self) -> Dict[str, Any]:
        """deposit_account_scenario.json 로드"""
        scenario_path = Path(__file__).parent.parent / "data" / "scenarios" / "deposit_account_scenario.json"
        with open(scenario_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _load_manual(self) -> str:
        """deposit_account.md 로드"""
        manual_path = Path(__file__).parent.parent / "data" / "docs" / "deposit_account.md"
        with open(manual_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _create_unified_knowledge(self) -> Dict[str, Any]:
        """통합 지식베이스 생성"""
        # scenario.json의 manual 섹션
        quick_answers = self.scenario_data.get("manual", {}).get("common_questions", {})
        
        # deposit_account.md에서 주요 섹션 추출
        manual_sections = self._parse_manual_sections()
        
        return {
            "quick_answers": {**quick_answers, **manual_sections["faq"]},
            "detailed_info": manual_sections["detailed"],
            "process_steps": self.scenario_data.get("manual", {}).get("process_steps", ""),
            "service_overview": self.scenario_data.get("manual", {}).get("service_overview", "")
        }
    
    def _parse_manual_sections(self) -> Dict[str, Any]:
        """매뉴얼을 섹션별로 파싱"""
        faq = {}
        detailed = {}
        
        # 간단한 파싱 로직 (실제로는 더 정교하게)
        if "한도거래제한계좌란?" in self.manual_data:
            faq["한도제한계좌"] = "금융거래 목적 확인 전까지 1일 출금 및 이체 한도가 제한되는 계좌입니다."
        
        if "평생계좌란?" in self.manual_data:
            faq["평생계좌"] = "고객이 기억하기 쉬운 자신만의 번호를 계좌에 부여하여 사용할 수 있는 서비스입니다."
        
        detailed["한도제한해제"] = "급여소득자는 재직증명서, 사업자는 사업자등록증명원 등을 제출하여 해제 가능합니다."
        
        return {"faq": faq, "detailed": detailed}
    
    def get_quick_answer(self, user_input: str) -> Optional[str]:
        """즉시 답변 가능한지 확인"""
        user_input_lower = user_input.lower()
        
        for keyword, answer in self.unified_knowledge["quick_answers"].items():
            if keyword in user_input_lower:
                return answer
        
        return None
    
    def get_full_knowledge_context(self) -> str:
        """전체 지식 컨텍스트를 문자열로 반환"""
        return f"""
## 즉시 답변 가능한 정보
{json.dumps(self.unified_knowledge['quick_answers'], ensure_ascii=False, indent=2)}

## 서비스 개요
{self.unified_knowledge['service_overview']}

## 처리 절차
{self.unified_knowledge['process_steps']}

## 상세 정보
{json.dumps(self.unified_knowledge['detailed_info'], ensure_ascii=False, indent=2)}
"""


class LLMIntentClassifier:
    """LLM 기반 의도 분류기"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=LLM_MODEL_NAME,
            temperature=0.1
        )
        self.prompts = self._load_prompts()
    
    def _load_prompts(self) -> Dict[str, str]:
        """의도 분류 프롬프트 로드"""
        prompt_path = Path(__file__).parent.parent / "config" / "intent_classification_prompts.yaml"
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    async def classify_intent(
        self, 
        user_input: str, 
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """사용자 의도 분류"""
        prompt = self.prompts["main_intent_classification"]["prompt"].format(
            user_input=user_input,
            current_stage=context.get("current_stage", "unknown"),
            stage_type=context.get("stage_type", "unknown"),
            last_system_message=context.get("last_system_message", "")
        )
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="You are an intent classifier. Always respond with valid JSON."),
                HumanMessage(content=prompt)
            ])
            
            result = json.loads(response.content)
            return result
            
        except Exception as e:
            print(f"Intent classification error: {e}")
            return {
                "intent": "REQUEST_CLARIFY",
                "confidence": 0.0,
                "reasoning": f"Classification failed: {str(e)}"
            }


class LLMEntityExtractor:
    """LLM 기반 개별 엔티티 추출기"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=LLM_MODEL_NAME,
            temperature=0.1
        )
        self.prompts = self._load_prompts()
    
    def _load_prompts(self) -> Dict[str, Any]:
        """엔티티 추출 프롬프트 로드"""
        prompt_path = Path(__file__).parent.parent / "config" / "entity_extraction_prompts.yaml"
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    async def extract_entity(
        self, 
        user_input: str, 
        field_key: str
    ) -> Optional[Any]:
        """단일 엔티티 추출"""
        if field_key not in self.prompts:
            return None
        
        prompt = self.prompts[field_key]["prompt"].format(user_input=user_input)
        
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=f"Extract {field_key} from user input. Return only the extracted value or null."),
                HumanMessage(content=prompt)
            ])
            
            # 응답 파싱
            content = response.content.strip()
            if content.lower() == "null" or not content:
                return None
            
            # boolean 처리
            if content.lower() in ["true", "false"]:
                return content.lower() == "true"
            
            return content
            
        except Exception as e:
            print(f"Entity extraction error for {field_key}: {e}")
            return None
    
    async def extract_all_entities(
        self, 
        user_input: str, 
        required_fields: List[str]
    ) -> Dict[str, Any]:
        """모든 필요한 엔티티를 병렬로 추출"""
        tasks = []
        for field_key in required_fields:
            tasks.append(self.extract_entity(user_input, field_key))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        extracted = {}
        for field_key, result in zip(required_fields, results):
            if not isinstance(result, Exception) and result is not None:
                extracted[field_key] = result
        
        return extracted


class ResponseGenerator:
    """최종 응답 생성기"""
    
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=LLM_MODEL_NAME,
            temperature=0.3
        )
    
    async def generate_response(
        self,
        user_input: str,
        quick_answer: Optional[str],
        intent_result: Dict[str, Any],
        extracted_entities: Dict[str, Any],
        rag_result: Optional[Dict[str, Any]],
        context: Dict[str, Any],
        knowledge_context: str
    ) -> Dict[str, Any]:
        """모든 정보를 종합하여 최종 응답 생성"""
        
        # 즉시 답변이 있으면 바로 반환
        if quick_answer:
            return {
                "type": "direct_answer",
                "message": quick_answer,
                "collected_info": {},
                "next_action": "continue_current_stage",
                "confidence": 1.0
            }
        
        # 응답 생성 프롬프트
        prompt = f"""
당신은 신한은행 입출금통장 개설 상담 AI입니다.

## 제공된 지식
{knowledge_context}

## 현재 상황
- 단계: {context.get('current_stage')}
- 수집된 정보: {json.dumps(context.get('collected_info', {}), ensure_ascii=False)}
- 필요한 정보: {context.get('required_fields', [])}

## 분석 결과
- 사용자 입력: "{user_input}"
- 의도: {intent_result.get('intent')} (신뢰도: {intent_result.get('confidence')})
- 추출된 정보: {json.dumps(extracted_entities, ensure_ascii=False)}
- RAG 검색: {rag_result.get('answer', 'N/A') if rag_result else 'N/A'}

## 응답 생성 규칙
1. 의도가 PROVIDE_INFO이고 정보가 추출되었으면 → 확인 메시지 + 다음 필요 정보 요청
2. 의도가 AFFIRM/DENY이고 yes/no 질문 단계면 → 다음 단계로 진행
3. 의도가 ASK_FAQ/ASK_COMPLEX면 → 질문에 답변 + 현재 단계 계속
4. 정보가 모두 수집되었으면 → 다음 단계로 진행
5. 불명확하면 → 재질의

생성할 응답:
{{
  "message": "사용자에게 전달할 자연스러운 한국어 응답",
  "collected_info": {{추출된 정보}},
  "next_action": "continue|next_stage|clarify",
  "confidence": 0.0-1.0
}}
"""

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="Generate a response based on the analysis. Return valid JSON."),
                HumanMessage(content=prompt)
            ])
            
            result = json.loads(response.content)
            return {
                "type": "generated_response",
                **result
            }
            
        except Exception as e:
            print(f"Response generation error: {e}")
            return {
                "type": "error",
                "message": "죄송합니다. 다시 한 번 말씀해주시겠어요?",
                "collected_info": {},
                "next_action": "clarify",
                "confidence": 0.0
            }


class UnifiedMainAgent:
    """통합 Main Agent - 모든 컴포넌트 조율"""
    
    def __init__(self):
        self.knowledge_manager = KnowledgeManager()
        self.intent_classifier = LLMIntentClassifier()
        self.entity_extractor = LLMEntityExtractor()
        self.response_generator = ResponseGenerator()
        
        # 시나리오 엔진은 기존 것 재사용
        from ..graph.simple_scenario_engine import simple_scenario_engine
        self.scenario_engine = simple_scenario_engine
    
    async def process_user_input(
        self,
        user_input: str,
        current_stage: str,
        collected_info: Dict[str, Any],
        last_system_message: str = ""
    ) -> Dict[str, Any]:
        """사용자 입력 처리 - 메인 엔트리포인트"""
        
        # 1. 컨텍스트 준비
        stage_info = self.scenario_engine.get_current_stage_info(current_stage)
        required_fields = [f["key"] for f in self.scenario_engine.get_required_fields_for_stage(current_stage)]
        
        context = {
            "current_stage": current_stage,
            "stage_type": stage_info.get("type", "unknown"),
            "collected_info": collected_info,
            "required_fields": required_fields,
            "last_system_message": last_system_message
        }
        
        # 2. 즉시 답변 체크 (동기)
        quick_answer = self.knowledge_manager.get_quick_answer(user_input)
        
        # 3. 병렬 처리 준비
        tasks = []
        
        # 3-1. 의도 분류 (항상)
        tasks.append(self.intent_classifier.classify_intent(user_input, context))
        
        # 3-2. 엔티티 추출 (필요한 필드가 있을 때만)
        if required_fields:
            tasks.append(self.entity_extractor.extract_all_entities(user_input, required_fields))
        else:
            tasks.append(asyncio.create_task(asyncio.sleep(0)))  # dummy task
        
        # 3-3. RAG 검색 (즉시 답변이 없고 질문 의도일 가능성이 있을 때)
        if not quick_answer and any(q in user_input.lower() for q in ["?", "뭐", "어떻게", "얼마"]):
            # RAG 검색은 실제 구현에서 추가
            tasks.append(self._search_rag(user_input))
        else:
            tasks.append(asyncio.create_task(asyncio.sleep(0)))  # dummy task
        
        # 4. 병렬 실행
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 5. 결과 언패킹
        intent_result = results[0] if not isinstance(results[0], Exception) else {"intent": "UNKNOWN", "confidence": 0.0}
        extracted_entities = results[1] if not isinstance(results[1], Exception) and isinstance(results[1], dict) else {}
        rag_result = results[2] if not isinstance(results[2], Exception) and isinstance(results[2], dict) else None
        
        # 6. 최종 응답 생성
        response = await self.response_generator.generate_response(
            user_input=user_input,
            quick_answer=quick_answer,
            intent_result=intent_result,
            extracted_entities=extracted_entities,
            rag_result=rag_result,
            context=context,
            knowledge_context=self.knowledge_manager.get_full_knowledge_context()
        )
        
        # 7. 시나리오 진행 처리
        if response.get("next_action") == "next_stage":
            next_stage = self.scenario_engine.get_next_stage(current_stage, user_input)
            response["next_stage"] = next_stage
            response["next_message"] = self.scenario_engine.get_stage_message(next_stage)
        else:
            response["continue_stage"] = current_stage
        
        return response
    
    async def _search_rag(self, user_input: str) -> Dict[str, Any]:
        """RAG 검색 (LanceDB 기반)"""
        try:
            from ..services.rag_service import rag_service
            
            # RAG 서비스가 초기화되지 않았다면 초기화
            if not rag_service.is_initialized():
                print("[UnifiedMainAgent] Initializing RAG service...")
                rag_service.initialize()
            
            # 질문에 대한 답변 검색
            result = await rag_service.answer_question(
                question=user_input,
                scenario_name="입출금통장 개설"
            )
            
            return {
                "answer": result.get("answer", ""),
                "confidence": 0.8,
                "sources": result.get("sources", [])
            }
            
        except Exception as e:
            print(f"[UnifiedMainAgent] RAG search error: {e}")
            # RAG 실패 시 fallback
            return {
                "answer": None,
                "confidence": 0.0,
                "sources": []
            }


# 전역 인스턴스
unified_main_agent = UnifiedMainAgent()