"""
GeneralMainAgent - 업무 미선택 시 일반 금융 상담을 담당하는 에이전트

주요 기능:
1. 일반적인 금융 질문에 대한 RAG 기반 답변
2. 사용자 니즈 파악 후 적절한 업무 추천
3. 자연스러운 업무 전환 가이드
4. 업무 선택을 강제하지 않는 유연한 상담
"""

import asyncio
from typing import Dict, List, Any, Optional
from langchain_core.messages import HumanMessage, AIMessage
from ..services.rag_service import rag_service
from ..core.config import LLM_MODEL_NAME
from ..graph.chains import generative_llm


class GeneralMainAgent:
    def __init__(self):
        self.available_services = {
            "didimdol": {
                "name": "디딤돌 대출",
                "description": "주택 구입을 위한 정부지원 대출",
                "keywords": ["디딤돌", "주택구입", "집구매", "내집마련", "주택대출"]
            },
            "jeonse": {
                "name": "전세자금 대출",
                "description": "전세 계약을 위한 임차보증금 대출",
                "keywords": ["전세", "임차", "보증금", "전세대출", "임대"]
            },
            "deposit_account": {
                "name": "입출금통장",
                "description": "기본 입출금 기능과 부가서비스를 제공하는 통장",
                "keywords": ["통장", "계좌", "입출금", "적금", "예금"]
            }
        }
        
        self.general_prompts = {
            "consultation": """당신은 신한은행의 친근하고 전문적인 금융 상담원입니다.

고객의 질문에 대해:
1. 먼저 질문이 특정 금융 상품/서비스에 관련된 것인지 판단하세요
2. 일반적인 금융 질문이라면 정확하고 도움이 되는 답변을 제공하세요
3. 특정 상품에 관심을 보인다면 자연스럽게 해당 서비스를 안내하세요
4. 상품 선택을 강요하지 말고, 고객이 편안하게 질문할 수 있도록 도와주세요

현재 제공 가능한 주요 서비스:
- 디딤돌 대출: 주택 구입을 위한 정부지원 대출
- 전세자금 대출: 전세 계약을 위한 임차보증금 대출  
- 입출금통장: 기본 입출금 기능과 부가서비스 제공

고객 질문: {user_input}

답변:""",

            "service_recommendation": """당신은 신한은행의 전문 금융 상담원입니다.

고객의 상황과 니즈를 분석하여 가장 적합한 금융 서비스를 추천해주세요.

고객 질문: {user_input}
이전 대화 컨텍스트: {context}

추천 기준:
1. 고객의 명시적/암시적 니즈 파악
2. 생활 상황 및 재정 상태 고려
3. 가장 도움이 될 수 있는 서비스 우선 추천
4. 여러 서비스가 도움이 된다면 우선순위와 함께 안내

서비스별 주요 특징:
- 디딤돌 대출: 주택구입, 신혼부부/청년 우대, 정부지원
- 전세자금 대출: 전세계약, 임차보증금, 빠른 승인
- 입출금통장: 기본 금융거래, 급여통장, 인터넷뱅킹

추천 및 안내:""",

            "rag_query": """다음 고객 질문을 분석하여 관련 정보를 검색하기 위한 적절한 쿼리를 생성하세요.

고객 질문: {user_input}

검색해야 할 정보:
1. 금융 상품 정보
2. 대출 조건 및 금리
3. 신청 절차 및 필요 서류
4. 수수료 및 혜택

생성된 검색 쿼리: """
        }

    async def process_user_input(
        self, 
        user_input: str, 
        context: Dict[str, Any],
        conversation_history: List[Dict] = None
    ) -> Dict[str, Any]:
        """
        사용자 입력을 처리하여 적절한 응답을 생성
        
        Returns:
            - response_text: 사용자에게 보여줄 응답
            - recommended_service: 추천하는 서비스 (있는 경우)
            - intent: 분류된 의도
            - needs_rag: RAG 검색이 필요한지 여부
        """
        
        try:
            # 1. 의도 분류 및 서비스 추천 확인
            intent_result = await self._classify_intent(user_input, context)
            
            # 2. RAG가 필요한 경우 검색 수행
            rag_results = None
            if intent_result.get("needs_rag", False):
                rag_results = await self._search_with_rag(user_input)
            
            # 3. 최종 응답 생성
            response = await self._generate_response(
                user_input, intent_result, rag_results, context
            )
            
            return {
                "response_text": response,
                "recommended_service": intent_result.get("recommended_service"),
                "intent": intent_result.get("intent"),
                "needs_service_transition": intent_result.get("needs_service_transition", False),
                "conversation_continues": True
            }
            
        except Exception as e:
            print(f"[GeneralMainAgent] Error processing input: {e}")
            return {
                "response_text": "죄송합니다. 일시적인 오류가 발생했습니다. 다시 한번 말씀해주시겠어요?",
                "recommended_service": None,
                "intent": "error",
                "needs_service_transition": False,
                "conversation_continues": True
            }

    async def _classify_intent(self, user_input: str, context: Dict) -> Dict[str, Any]:
        """사용자 의도 분류 및 서비스 추천 (LLM 기반)"""
        
        # LLM 기반 의도 분류 및 서비스 감지
        intent_prompt = f"""다음 고객 질문을 분석하여 의도를 분류하고 적절한 금융 서비스를 추천하세요.

고객 질문: "{user_input}"

이용 가능한 서비스:
- didimdol: 디딤돌 대출 (주택 구입, 집 사기, 내집마련, 주택구매, 신혼부부/청년 우대)
- jeonse: 전세자금 대출 (전세, 임차, 보증금, 전세대출, 임대차)  
- deposit_account: 입출금통장 (통장, 계좌, 입출금, 계좌개설, 통장만들기, 급여통장)

분석 기준:
1. 고객이 구체적인 상품명이나 서비스를 언급했는가?
2. 고객이 특정 목적(주택구입, 전세, 통장개설 등)을 명시했는가?
3. 고객의 니즈가 어느 서비스와 가장 잘 맞는가?

의도 분류:
- general_question: 일반적인 금융 질문, 인사말
- service_inquiry: 특정 서비스에 대한 문의나 정보 요청
- service_request: 특정 서비스 신청이나 시작 의도
- comparison_request: 여러 상품 비교 요청

반드시 아래 형식으로만 응답하세요:
- 의도: [general_question|service_inquiry|service_request|comparison_request]
- 추천 서비스: [didimdol|jeonse|deposit_account|없음]
- RAG 필요: 예
- 서비스 전환 필요: [예|아니오]
"""

        try:
            if generative_llm:
                result = await generative_llm.ainvoke([HumanMessage(content=intent_prompt)])
                intent_text = result.content
                print(f"[GeneralMainAgent] LLM Intent Analysis: {intent_text}")
                
                return self._parse_intent_result(intent_text)
        except Exception as e:
            print(f"[GeneralMainAgent] Intent classification error: {e}")
            
        # 폴백: 키워드 기반 분류 (보조적 역할)
        detected_service = self._detect_service_keywords(user_input)
        return {
            "intent": "service_inquiry" if detected_service else "general_question",
            "recommended_service": detected_service,
            "needs_rag": True,
            "needs_service_transition": bool(detected_service)
        }

    def _detect_service_keywords(self, user_input: str) -> Optional[str]:
        """키워드 기반 서비스 감지"""
        user_input_lower = user_input.lower()
        
        for service_id, service_info in self.available_services.items():
            for keyword in service_info["keywords"]:
                if keyword in user_input_lower:
                    return service_id
        
        return None

    def _parse_intent_result(self, intent_text: str) -> Dict[str, Any]:
        """LLM 응답에서 의도 분류 결과 파싱"""
        
        # 기본값 설정
        result = {
            "intent": "general_question",
            "recommended_service": None,
            "needs_rag": True,
            "needs_service_transition": False
        }
        
        # 텍스트를 소문자로 변환하여 파싱
        text_lower = intent_text.lower()
        
        # 의도 파싱
        intent_mapping = {
            "general_question": "general_question",
            "service_inquiry": "service_inquiry", 
            "service_request": "service_request",
            "comparison_request": "comparison_request"
        }
        
        for key, value in intent_mapping.items():
            if f"의도: {key}" in text_lower or f"- 의도: {key}" in text_lower:
                result["intent"] = value
                break
        
        # 추천 서비스 파싱
        service_mapping = {
            "didimdol": "didimdol",
            "jeonse": "jeonse", 
            "deposit_account": "deposit_account"
        }
        
        for service_key in service_mapping:
            if f"추천 서비스: {service_key}" in text_lower or f"- 추천 서비스: {service_key}" in text_lower:
                result["recommended_service"] = service_mapping[service_key]
                break
        
        # RAG 필요 여부 파싱
        if "rag 필요: 예" in text_lower or "- rag 필요: 예" in text_lower:
            result["needs_rag"] = True
        elif "rag 필요: 아니오" in text_lower or "- rag 필요: 아니오" in text_lower:
            result["needs_rag"] = False
        
        # 서비스 전환 필요 여부 파싱
        if ("서비스 전환 필요: 예" in text_lower or 
            "- 서비스 전환 필요: 예" in text_lower or
            result["intent"] in ["service_request", "service_inquiry"]):
            result["needs_service_transition"] = bool(result["recommended_service"])
        
        print(f"[GeneralMainAgent] Parsed result: {result}")
        return result

    async def _search_with_rag(self, user_input: str) -> Optional[str]:
        """RAG 기반 정보 검색"""
        try:
            if rag_service:
                # RAG 쿼리 생성
                query_prompt = self.general_prompts["rag_query"].format(user_input=user_input)
                
                if generative_llm:
                    query_result = await generative_llm.ainvoke([HumanMessage(content=query_prompt)])
                    search_query = query_result.content.strip()
                else:
                    search_query = user_input
                
                # RAG 검색 수행
                rag_result = await rag_service.search_async(search_query, top_k=3)
                
                if rag_result and rag_result.get("documents"):
                    return "\n".join(rag_result["documents"])
                    
        except Exception as e:
            print(f"[GeneralMainAgent] RAG search error: {e}")
        
        return None

    async def _generate_response(
        self, 
        user_input: str, 
        intent_result: Dict, 
        rag_results: Optional[str],
        context: Dict
    ) -> str:
        """최종 응답 생성"""
        
        intent = intent_result.get("intent", "general_question")
        recommended_service = intent_result.get("recommended_service")
        
        # 프롬프트 선택
        if intent == "service_request" and recommended_service:
            prompt_template = self.general_prompts["service_recommendation"]
        else:
            prompt_template = self.general_prompts["consultation"]
        
        # 프롬프트 구성
        prompt_kwargs = {
            "user_input": user_input,
            "context": str(context)
        }
        
        # RAG 결과가 있으면 추가
        if rag_results:
            enhanced_prompt = prompt_template + f"\n\n관련 정보:\n{rag_results}\n\n위 정보를 참고하여 답변하세요."
        else:
            enhanced_prompt = prompt_template
        
        try:
            if generative_llm:
                final_prompt = enhanced_prompt.format(**prompt_kwargs)
                result = await generative_llm.ainvoke([HumanMessage(content=final_prompt)])
                response = result.content
                
                # 서비스 추천이 있는 경우 자연스럽게 안내 추가
                if recommended_service and intent_result.get("needs_service_transition"):
                    service_info = self.available_services[recommended_service]
                    response += f"\n\n{service_info['name']} 상담을 원하시면 언제든 말씀해주세요. 더 자세한 안내를 도와드리겠습니다."
                
                return response
            else:
                return "죄송합니다. 현재 상담 서비스를 이용할 수 없습니다."
                
        except Exception as e:
            print(f"[GeneralMainAgent] Response generation error: {e}")
            return "죄송합니다. 답변 생성 중 오류가 발생했습니다. 다시 말씀해주시겠어요?"

    def get_available_services(self) -> Dict[str, Dict]:
        """이용 가능한 서비스 목록 반환"""
        return self.available_services.copy()

    def is_service_transition_needed(self, intent_result: Dict) -> bool:
        """서비스 전환이 필요한지 판단"""
        return intent_result.get("needs_service_transition", False)