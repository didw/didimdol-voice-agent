# backend/app/graph/agent.py
import json
import yaml
import asyncio
from pathlib import Path
from typing import Dict, Optional, Sequence, Literal, Any, List, Union, cast, AsyncGenerator
import traceback

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

from .state import AgentState, ScenarioAgentOutput, PRODUCT_TYPES
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from .models import (
    next_stage_decision_parser,
    initial_task_decision_parser,
    main_router_decision_parser,
    ActionModel,
    expanded_queries_parser
)
from .utils import (
    ALL_PROMPTS,
    ALL_SCENARIOS_DATA,
    get_active_scenario_data,
    load_knowledge_base_content_async,
    format_messages_for_prompt,
    format_transitions_for_prompt,
)
from .chains import (
    json_llm,
    generative_llm,
    synthesizer_chain,
    invoke_scenario_agent_logic
)
import re
from ..services.rag_service import rag_service
from ..services.web_search_service import web_search_service

# --- Flow Tracking ---

def log_node_execution(node_name: str, input_info: str = "", output_info: str = ""):
    """간결한 노드 실행 추적 로깅"""
    if input_info and output_info:
        print(f"🔄 [{node_name}] {input_info} → {output_info}")
    elif input_info:
        print(f"🔄 [{node_name}] {input_info}")
    else:
        print(f"🔄 [{node_name}]")

# --- Helper Functions for Information Collection ---

# 키워드 기반 추출 로직 제거 - Entity Agent 사용으로 대체

def check_required_info_completion(collected_info: Dict, required_fields: List[Dict]) -> tuple[bool, List[str]]:
    """필수 정보 수집 완료 여부 확인"""
    missing_fields = []
    
    for field in required_fields:
        if field["required"] and field["key"] not in collected_info:
            missing_fields.append(field["display_name"])
    
    is_complete = len(missing_fields) == 0
    return is_complete, missing_fields

def generate_missing_info_prompt(missing_fields: List[str], collected_info: Dict) -> str:
    """부족한 정보에 대한 자연스러운 요청 메시지 생성"""
    if len(missing_fields) == 1:
        return f"{missing_fields[0]}에 대해서 알려주시겠어요?"
    elif len(missing_fields) == 2:
        return f"{missing_fields[0]}과(와) {missing_fields[1]}에 대해서 알려주시겠어요?"
    else:
        field_list = ", ".join(missing_fields[:-1])
        return f"{field_list}, 그리고 {missing_fields[-1]}에 대해서 알려주시겠어요?"

def get_next_missing_info_group_stage(collected_info: Dict, required_fields: List[Dict]) -> str:
    """수집된 정보를 바탕으로 다음에 물어볼 그룹 스테이지 결정"""
    # 그룹별 정보 확인
    group1_fields = ["loan_purpose_confirmed", "marital_status"]
    group2_fields = ["has_home", "annual_income"] 
    group3_fields = ["target_home_price"]
    
    print(f"현재 수집된 정보: {collected_info}")
    
    # 각 그룹에서 누락된 정보가 있는지 확인
    group1_missing = any(field not in collected_info for field in group1_fields)
    group2_missing = any(field not in collected_info for field in group2_fields)
    group3_missing = any(field not in collected_info for field in group3_fields)
    
    print(f"그룹별 누락 상태 - Group1: {group1_missing}, Group2: {group2_missing}, Group3: {group3_missing}")
    
    if group1_missing:
        return "ask_missing_info_group1"
    elif group2_missing:
        return "ask_missing_info_group2"
    elif group3_missing:
        return "ask_missing_info_group3"
    else:
        return "eligibility_assessment"

def generate_group_specific_prompt(stage_id: str, collected_info: Dict) -> str:
    """그룹별로 이미 수집된 정보를 제외하고 맞춤형 질문 생성"""
    print(f"질문 생성 - stage_id: {stage_id}, collected_info: {collected_info}")
    
    if stage_id == "ask_missing_info_group1":
        missing = []
        has_loan_purpose = collected_info.get("loan_purpose_confirmed", False)
        has_marital_status = "marital_status" in collected_info
        
        if not has_loan_purpose:
            missing.append("대출 목적(주택 구입용인지)")
        if not has_marital_status:
            missing.append("혼인 상태")
        
        print(f"Group1 누락 정보: {missing}")
        
        if len(missing) == 2:
            return "몇 가지 더 확인해볼게요. 대출 목적과 혼인 상태는 어떻게 되시나요?"
        elif "대출 목적(주택 구입용인지)" in missing:
            return "대출 목적을 확인해볼게요. 주택 구입 목적이 맞으신가요?"
        elif "혼인 상태" in missing:
            return "혼인 상태는 어떻게 되시나요? (미혼/기혼/예비부부)"
        else:
            # Group1의 모든 정보가 수집된 경우 Group2로 넘어가야 함
            return "추가 정보를 알려주시겠어요?"
            
    elif stage_id == "ask_missing_info_group2":
        missing = []
        if "has_home" not in collected_info:
            missing.append("주택 소유 여부")
        if "annual_income" not in collected_info:
            missing.append("연소득")
            
        if len(missing) == 2:
            return "현재 주택 소유 여부와 연소득은 어느 정도 되시나요?"
        elif "주택 소유 여부" in missing:
            return "현재 소유하고 계신 주택이 있으신가요?"
        else:
            return "연소득은 어느 정도 되시나요? (세전 기준)"
            
    elif stage_id == "ask_missing_info_group3":
        return "구매 예정이신 주택 가격은 어느 정도로 생각하고 계신가요?"
    
    return "추가 정보를 알려주시겠어요?"

# --- LangGraph Node Functions ---

async def entry_point_node(state: AgentState) -> AgentState:
    user_text = state.get("user_input_text", "")
    product = state.get("current_product_type", "None")
    log_node_execution("Entry", f"input='{user_text[:20]}...', product={product}")
    if not ALL_SCENARIOS_DATA or not ALL_PROMPTS:
        error_msg = "Service initialization failed (Cannot load scenarios or prompts)."
        return {**state, "error_message": error_msg, "final_response_text_for_tts": error_msg, "is_final_turn_response": True}

    # Reset turn-specific state
    turn_defaults = {
        "stt_result": None, "main_agent_routing_decision": None, "main_agent_direct_response": None,
        "scenario_agent_output": None, "final_response_text_for_tts": None,
        "is_final_turn_response": False, "error_message": None,
        "active_scenario_data": None, "active_knowledge_base_content": None,
        "loan_selection_is_fresh": False, "factual_response": None, "action_plan": [],
    }
    
    current_product = state.get("current_product_type")
    updated_state = {**state, **turn_defaults, "current_product_type": current_product}
    
    # Load active scenario data if a product is selected
    active_scenario = get_active_scenario_data(updated_state)
    if active_scenario:
        updated_state["active_scenario_data"] = active_scenario
        updated_state["active_scenario_name"] = active_scenario.get("scenario_name", "Unknown Product")
        if not updated_state.get("current_scenario_stage_id"):
            updated_state["current_scenario_stage_id"] = active_scenario.get("initial_stage_id")
    else:
        updated_state["active_scenario_name"] = "Not Selected"

    # Add user input to message history
    user_text = updated_state.get("user_input_text")
    if user_text:
        messages = list(updated_state.get("messages", []))
        if not messages or not (isinstance(messages[-1], HumanMessage) and messages[-1].content == user_text):
            messages.append(HumanMessage(content=user_text))
        updated_state["messages"] = messages
        updated_state["stt_result"] = user_text
    
    # 시나리오 자동 진행 로직
    scenario_continuation = _check_scenario_continuation(state, updated_state)
    if scenario_continuation:
        updated_state.update(scenario_continuation)
        
    return cast(AgentState, updated_state)

def _check_scenario_continuation(prev_state: AgentState, current_state: AgentState) -> dict:
    """시나리오 연속 진행이 필요한지 확인하고 자동 설정"""
    
    # 이전 상태에서 시나리오 연속성이 준비되어 있고, 현재 사용자 입력이 있는 경우
    if (prev_state.get("scenario_ready_for_continuation") and 
        prev_state.get("current_product_type") and 
        current_state.get("user_input_text")):
        
        print("🔄 시나리오 자동 진행 모드 활성화")
        print(f"   제품: {prev_state.get('current_product_type')}")
        print(f"   시나리오: {prev_state.get('active_scenario_name')}")
        
        return {
            "action_plan": ["invoke_scenario_agent"],
            "scenario_ready_for_continuation": False,  # 자동 진행 후 리셋
            "scenario_awaiting_user_response": False,
            # 이전 상태에서 필요한 정보 복원
            "current_product_type": prev_state.get("current_product_type"),
            "current_scenario_stage_id": prev_state.get("current_scenario_stage_id"),
            "collected_product_info": prev_state.get("collected_product_info", {})
        }
    
    return {}

async def main_agent_router_node(state: AgentState) -> AgentState:
    user_input = state.get("stt_result", "")
    current_product_type = state.get("current_product_type")
    mode = "business_guidance" if not current_product_type else "task_management"
    log_node_execution("Orchestrator", f"mode={mode}, input='{user_input[:20]}...'")
    if not json_llm:
        return {**state, "error_message": "Orchestrator service unavailable (LLM not initialized).", "is_final_turn_response": True}

    user_input = state.get("stt_result", "")
    current_product_type = state.get("current_product_type")
    
    # LLM 기반 대화 처리 및 Worker 결정
    prompt_key = 'business_guidance_prompt' if not current_product_type else 'task_management_prompt'
    print(f"Main Agent using prompt: '{prompt_key}'")

    prompt_template = ALL_PROMPTS.get('main_agent', {}).get(prompt_key, '')
    if not prompt_template:
        return {**state, "error_message": "Router prompt not found.", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

    parser = initial_task_decision_parser if not current_product_type else main_router_decision_parser
    format_instructions = parser.get_format_instructions()
    
    try:
        prompt_kwargs = {"user_input": user_input, "format_instructions": format_instructions}
        
        # business_guidance_prompt에 서비스 설명 추가
        if not current_product_type:
            # service_descriptions.yaml 로드
            service_desc_path = Path(__file__).parent.parent / "config" / "service_descriptions.yaml"
            if service_desc_path.exists():
                with open(service_desc_path, 'r', encoding='utf-8') as f:
                    service_data = yaml.safe_load(f)
                    
                # 서비스 설명 포맷팅
                service_descriptions = ""
                for service_id in ["didimdol", "jeonse", "deposit_account"]:
                    if service_id in service_data:
                        svc = service_data[service_id]
                        service_descriptions += f"\n**{svc['name']}** ({service_id})\n"
                        service_descriptions += f"- 대상: {svc['target']}\n"
                        service_descriptions += f"- 설명: {svc['summary'].strip()}\n"
                        if 'benefits' in svc:
                            service_descriptions += f"- 주요 혜택: {', '.join(svc['benefits'][:2])}\n"
                
                prompt_kwargs["service_descriptions"] = service_descriptions
            else:
                # 폴백: 기본 설명 사용
                prompt_kwargs["service_descriptions"] = """
**디딤돌 대출** (didimdol)
- 대상: 무주택 서민 (연소득 6-7천만원 이하)
- 설명: 정부 지원 주택구입자금 대출, 최대 3-4억원, 연 2.15~2.75%

**전세 대출** (jeonse)  
- 대상: 무주택 세대주
- 설명: 전세 보증금 대출, 보증금의 80-90%, 만기일시상환

**입출금통장** (deposit_account)
- 대상: 모든 고객
- 설명: 기본 계좌, 평생계좌 서비스, 체크카드/인터넷뱅킹 동시 신청
"""
        
        if current_product_type:
             active_scenario_data = get_active_scenario_data(state) or {}
             current_stage_id = state.get("current_scenario_stage_id", "N/A")
             current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
             valid_choices = current_stage_info.get("choices", []) 
             available_types = ", ".join([ALL_SCENARIOS_DATA[pt]["scenario_name"] for pt in state.get("available_product_types", []) if pt in ALL_SCENARIOS_DATA])
             
             # 업무 관련 JSON 정보 추가
             task_context = {
                 "collected_info": state.get("collected_product_info", {}),
                 "current_stage": current_stage_info,
                 "stage_id": current_stage_id,
                 "expected_info": current_stage_info.get("expected_info_key", ""),
                 "valid_choices": valid_choices
             }
             
             # 매뉴얼 정보 로드
             product_type = state.get("current_product_type")
             manual_content = await load_knowledge_base_content_async(product_type) if product_type else ""
             
             prompt_kwargs.update({
                "active_scenario_name": state.get("active_scenario_name", "Not Selected"),
                "formatted_messages_history": format_messages_for_prompt(state.get("messages", [])[:-1]),
                "task_context_json": json.dumps(task_context, ensure_ascii=False, indent=2),
                "manual_content": manual_content[:2000] if manual_content else "매뉴얼 정보 없음",
                "available_product_types_display": available_types
             })
        else:
            # 초기 프롬프트에 필요한 available_product_types_list를 추가합니다.
            available_types_list = state.get("available_product_types", [])
            available_services = {
                "didimdol": "디딤돌 대출 - 주택구입을 위한 정부지원 대출",
                "jeonse": "전세자금대출 - 전세 보증금 마련을 위한 대출", 
                "deposit_account": "입출금통장 - 일상적인 금융거래를 위한 기본 계좌"
            }
            
            service_descriptions = [f"- {available_services.get(pt, pt)}" for pt in available_types_list]
            
            prompt_kwargs.update({
                "available_product_types_list": available_types_list,
                "available_services_description": "\n".join(service_descriptions)
            })
        
        prompt_filled = prompt_template.format(**prompt_kwargs)
        response = await json_llm.ainvoke([HumanMessage(content=prompt_filled)])
        raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
        decision = parser.parse(raw_content)

        # 새로운 ActionModel 구조를 사용하도록 상태 업데이트
        action_plan_models = decision.actions
        action_plan_tools = [action.tool for action in action_plan_models]

        new_state = {}
        if hasattr(decision, 'direct_response') and decision.direct_response:
            new_state["main_agent_direct_response"] = decision.direct_response

        system_log = f"Main Agent Plan: actions={[f'{a.tool}({a.tool_input})' for a in action_plan_models]}"
        updated_messages = list(state.get("messages", [])) + [SystemMessage(content=system_log)]
        new_state["messages"] = updated_messages

        # 초기 상태 분기 처리: action_plan_models 자체를 수정하여 일관성 유지
        if not current_product_type:
            first_action = action_plan_models[0] if action_plan_models else None
            if first_action:
                if first_action.tool == "set_product_type":
                    new_state["loan_selection_is_fresh"] = True
                elif first_action.tool == "invoke_qa_agent_general":
                    # action_plan_models의 tool 이름을 직접 변경
                    first_action.tool = "invoke_qa_agent"
                    new_state["active_scenario_name"] = "General Financial Advice"
                elif first_action.tool == "clarify_product_type":
                    # action_plan_models의 tool 이름을 직접 변경
                    first_action.tool = "select_product_type"

        # 최종적으로 결정된 모델에서 action_plan과 action_plan_struct를 생성
        new_state["action_plan"] = [model.tool for model in action_plan_models]
        new_state["action_plan_struct"] = [model.model_dump() for model in action_plan_models]

        action_plan = new_state.get('action_plan', [])
        direct_resp = new_state.get('main_agent_direct_response', '')
        if direct_resp:
            log_node_execution("Orchestrator", output_info=f"direct_response='{direct_resp[:30]}...'")
        else:
            log_node_execution("Orchestrator", output_info=f"plan={action_plan}")
        return new_state

    except Exception as e:
        print(f"Main Agent Orchestrator Error: {e}"); traceback.print_exc()
        err_msg = "Error processing request. Please try again."
        return {**state, "error_message": err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

async def factual_answer_node(state: AgentState) -> dict:
    original_question = state.get("stt_result", "")
    log_node_execution("RAG_Worker", f"query='{original_question[:30]}...'")
    original_question = state.get("stt_result", "")
    messages = state.get("messages", [])
    chat_history = format_messages_for_prompt(messages[:-1]) if len(messages) > 1 else "No previous conversation."
    scenario_name = state.get("active_scenario_name", "General Financial Advice")

    if not rag_service.is_ready():
        print("Warning: RAG service is not ready. Using fallback response.")
        return {"factual_response": "죄송합니다, 현재 정보 검색 기능에 문제가 발생하여 답변을 드릴 수 없습니다. 잠시 후 다시 시도해 주세요."}

    all_queries = [original_question]
    try:
        # 1. 질문 확장
        print("--- Generating expanded queries... ---")
        expansion_prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('rag_query_expansion_prompt')
        if not expansion_prompt_template:
            raise ValueError("RAG query expansion prompt not found.")
        
        expansion_prompt = ChatPromptTemplate.from_template(expansion_prompt_template)
        
        expansion_chain = expansion_prompt | json_llm | expanded_queries_parser
        expanded_result = await expansion_chain.ainvoke({
            "scenario_name": scenario_name,
            "chat_history": chat_history,
            "user_question": original_question
        })
        
        if expanded_result and expanded_result.queries:
            all_queries.extend(expanded_result.queries)
            print(f"Expanded queries generated: {expanded_result.queries}")
        else:
            print("Query expansion did not produce results. Using original question only.")

    except Exception as e:
        # 질문 확장에 실패하더라도, 원본 질문으로 계속 진행
        print(f"Could not expand query due to an error: {e}. Proceeding with original question.")

    try:
        # 2. RAG 파이프라인 호출 (원본 + 확장 질문)
        print(f"Invoking RAG pipeline with {len(all_queries)} queries.")
        factual_response = await rag_service.answer_question(all_queries, original_question)
        print(f"RAG response: {factual_response[:100]}...")
    except Exception as e:
        print(f"Factual Answer Node Error (RAG): {e}")
        factual_response = "정보를 검색하는 중 오류가 발생했습니다."

    # 다음 액션을 위해 plan과 struct에서 현재 액션 제거
    updated_plan = state.get("action_plan", []).copy()
    if updated_plan:
        updated_plan.pop(0)
    
    updated_struct = state.get("action_plan_struct", []).copy()
    if updated_struct:
        updated_struct.pop(0)

    log_node_execution("RAG_Worker", output_info=f"response='{factual_response[:40]}...'")
    return {"factual_response": factual_response, "action_plan": updated_plan, "action_plan_struct": updated_struct}

async def web_search_node(state: AgentState) -> dict:
    """
    Web Search Worker - 외부 정보 검색 전문 처리
    """
    action_struct = state.get("action_plan_struct", [{}])[0]
    query = action_struct.get("tool_input", {}).get("query", "")
    log_node_execution("Web_Worker", f"query='{query[:30]}...'")
    action_struct = state.get("action_plan_struct", [{}])[0]
    query = action_struct.get("tool_input", {}).get("query", "")
    
    if not query:
        return {"factual_response": "무엇에 대해 검색할지 알려주세요."}

    # 1. Perform web search
    search_results = await web_search_service.asearch(query)
    
    # 2. Synthesize a natural language answer from the results
    try:
        synthesis_prompt = ChatPromptTemplate.from_messages([
            ("system", "You are a helpful AI assistant. Your task is to synthesize the provided web search results into a concise and natural-sounding answer to the user's question. Respond in Korean."),
            ("human", "User Question: {query}\n\nWeb Search Results:\n---\n{search_results}\n---\n\nSynthesized Answer:")
        ])
        
        synthesis_chain = synthesis_prompt | generative_llm
        response = await synthesis_chain.ainvoke({"query": query, "search_results": search_results})
        final_answer = response.content.strip()
        print(f"Synthesized web search answer: {final_answer[:100]}...")

    except Exception as e:
        print(f"Error synthesizing web search results: {e}")
        final_answer = "웹 검색 결과를 요약하는 중 오류가 발생했습니다. 원본 검색 결과는 다음과 같습니다.\n\n" + search_results

    # 다음 액션을 위해 plan과 struct에서 현재 액션 제거
    updated_plan = state.get("action_plan", []).copy()
    if updated_plan:
        updated_plan.pop(0)
    
    updated_struct = state.get("action_plan_struct", []).copy()
    if updated_struct:
        updated_struct.pop(0)
        
    # 웹 검색 결과를 사실 기반 답변으로 간주하여 factual_response에 저장
    log_node_execution("Web_Worker", output_info=f"response='{final_answer[:40]}...'")
    return {"factual_response": final_answer, "action_plan": updated_plan, "action_plan_struct": updated_struct}

async def call_scenario_agent_node(state: AgentState) -> AgentState:
    user_input = state.get("stt_result", "")
    scenario_name = state.get("active_scenario_name", "N/A")
    log_node_execution("Scenario_NLU", f"scenario={scenario_name}, input='{user_input[:20]}...'")
    user_input = state.get("stt_result", "")
    active_scenario_data = get_active_scenario_data(state)
    if not active_scenario_data or not user_input:
        return {**state, "scenario_agent_output": cast(ScenarioAgentOutput, {"intent": "error_missing_data", "is_scenario_related": False})}
    
    current_stage_id = state.get("current_scenario_stage_id", active_scenario_data.get("initial_stage_id"))
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})

    output = await invoke_scenario_agent_logic(
        user_input=user_input,
        current_stage_prompt=current_stage_info.get("prompt", ""),
        expected_info_key=current_stage_info.get("expected_info_key"),
        messages_history=state.get("messages", [])[:-1],
        scenario_name=active_scenario_data.get("scenario_name", "Consultation")
    )
    intent = output.get("intent", "N/A")
    
    entities = list(output.get("entities", {}).keys())
    log_node_execution("Scenario_NLU", output_info=f"intent={intent}, entities={entities}")
    return {**state, "scenario_agent_output": output}

async def process_scenario_logic_node(state: AgentState) -> AgentState:
    current_stage_id = state.get("current_scenario_stage_id", "N/A")
    scenario_name = state.get("active_scenario_name", "N/A")
    log_node_execution("Scenario_Flow", f"scenario={scenario_name}, stage={current_stage_id}")
    active_scenario_data = get_active_scenario_data(state)
    current_stage_id = state.get("current_scenario_stage_id")
    
    # 스테이지 ID가 없는 경우 초기 스테이지로 설정
    if not current_stage_id:
        current_stage_id = active_scenario_data.get("initial_stage_id", "greeting")
        print(f"스테이지 ID가 없어서 초기 스테이지로 설정: {current_stage_id}")
    
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
    print(f"현재 스테이지: {current_stage_id}, 스테이지 정보: {current_stage_info.keys()}")
    collected_info = state.get("collected_product_info", {}).copy()
    scenario_output = state.get("scenario_agent_output")
    user_input = state.get("stt_result", "")
    
    # 개선된 다중 정보 수집 처리
    print(f"스테이지 정보 확인 - collect_multiple_info: {current_stage_info.get('collect_multiple_info')}")
    if current_stage_info.get("collect_multiple_info"):
        print("--- 다중 정보 수집 모드 ---")
        return await process_multiple_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, user_input)
    
    # 기존 단일 정보 수집 처리
    return await process_single_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, scenario_output, user_input)

async def process_multiple_info_collection(state: AgentState, active_scenario_data: Dict, current_stage_id: str, current_stage_info: Dict, collected_info: Dict, user_input: str) -> AgentState:
    """다중 정보 수집 처리 (개선된 그룹별 방식)"""
    required_fields = active_scenario_data.get("required_info_fields", [])
    
    # 현재 스테이지가 정보 수집 단계인지 확인
    print(f"현재 스테이지 ID: {current_stage_id}")
    if current_stage_id in ["info_collection_guidance", "process_collected_info", "ask_missing_info_group1", "ask_missing_info_group2", "ask_missing_info_group3", "eligibility_assessment"]:
        
        # Entity Agent를 사용한 정보 추출
        if user_input:
            from ..agents.entity_agent import entity_agent
            
            # Entity Agent로 정보 추출
            extraction_result = await entity_agent.process_slot_filling(user_input, required_fields, collected_info)
            
            # 추출된 정보 업데이트
            collected_info = extraction_result["collected_info"]
            print(f"Entity Agent 추출 결과: {extraction_result['extracted_entities']}")
            print(f"최종 업데이트된 수집 정보: {collected_info}")
        
        # 정보 수집 완료 여부 확인
        is_complete, missing_field_names = check_required_info_completion(collected_info, required_fields)
        
        if current_stage_id == "info_collection_guidance":
            # 초기 정보 안내 후 바로 다음 그룹 질문 결정
            if is_complete:
                next_stage_id = "eligibility_assessment"
                response_text = "네, 모든 정보가 수집되었습니다. 이제 자격 요건을 확인해보겠습니다."
            else:
                # 수집된 정보에 따라 다음 그룹 질문 결정
                next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
                if next_stage_id == "eligibility_assessment":
                    response_text = "네, 모든 정보를 확인했습니다! 말씀해주신 조건으로 디딤돌 대출 신청이 가능해 보입니다. 이제 신청에 필요한 서류와 절차를 안내해드릴게요."
                else:
                    response_text = f"네, 말씀해주신 정보 확인했습니다! {generate_group_specific_prompt(next_stage_id, collected_info)}"
                print(f"info_collection_guidance -> {next_stage_id}, 응답: {response_text}")
                
        elif current_stage_id == "process_collected_info":
            # 수집된 정보를 바탕으로 다음 그룹 결정
            if is_complete:
                next_stage_id = "eligibility_assessment"
                response_text = "네, 모든 정보를 확인했습니다! 말씀해주신 조건으로 디딤돌 대출 신청이 가능해 보입니다. 이제 신청에 필요한 서류와 절차를 안내해드릴게요."
            else:
                next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
                response_text = generate_group_specific_prompt(next_stage_id, collected_info)
                print(f"다음 단계로 이동: {next_stage_id}, 질문: {response_text}")
                
        elif current_stage_id.startswith("ask_missing_info_group"):
            # 그룹별 질문 처리 후 다음 단계 결정
            if is_complete:
                next_stage_id = "eligibility_assessment"
                response_text = "네, 모든 정보를 확인했습니다! 말씀해주신 조건으로 디딤돌 대출 신청이 가능해 보입니다. 이제 신청에 필요한 서류와 절차를 안내해드릴게요."
            else:
                next_stage_id = get_next_missing_info_group_stage(collected_info, required_fields)
                # 같은 그룹이면 그대로, 다른 그룹이면 새로운 질문
                if next_stage_id == current_stage_id:
                    # 같은 그룹 내에서 아직 더 수집할 정보가 있는 경우
                    response_text = generate_group_specific_prompt(next_stage_id, collected_info)
                else:
                    # 다음 그룹으로 넘어가는 경우
                    response_text = generate_group_specific_prompt(next_stage_id, collected_info)
                    
        elif current_stage_id == "eligibility_assessment":
            # 자격 검토 완료 후 서류 안내로 자동 진행
            next_stage_id = "application_documents_guidance"
            response_text = active_scenario_data.get("stages", {}).get("application_documents_guidance", {}).get("prompt", "서류 안내를 진행하겠습니다.")
            print(f"자격 검토 완료 -> 서류 안내 단계로 이동")
            
        else:
            next_stage_id = current_stage_info.get("default_next_stage_id", "eligibility_assessment")
            response_text = current_stage_info.get("prompt", "")
        
        # 응답 텍스트가 설정되지 않은 경우 기본값 사용
        if "response_text" not in locals():
            response_text = current_stage_info.get("prompt", "추가 정보를 알려주시겠어요?")
        
        # 다음 액션을 위해 plan과 struct에서 현재 액션 제거 (무한 루프 방지)
        updated_plan = state.get("action_plan", []).copy()
        if updated_plan:
            updated_plan.pop(0)
        
        updated_struct = state.get("action_plan_struct", []).copy()
        if updated_struct:
            updated_struct.pop(0)
            
        return {
            **state, 
            "current_scenario_stage_id": next_stage_id,
            "collected_product_info": collected_info,
            "final_response_text_for_tts": response_text,
            "is_final_turn_response": True,
            "action_plan": updated_plan,
            "action_plan_struct": updated_struct
        }
    
    # 일반 스테이지는 기존 로직으로 처리
    return await process_single_info_collection(state, active_scenario_data, current_stage_id, current_stage_info, collected_info, state.get("scenario_agent_output"), user_input)

async def process_single_info_collection(state: AgentState, active_scenario_data: Dict, current_stage_id: str, current_stage_info: Dict, collected_info: Dict, scenario_output: Optional[ScenarioAgentOutput], user_input: str) -> AgentState:
    """기존 단일 정보 수집 처리"""

    if scenario_output and scenario_output.get("is_scenario_related"):
        entities = scenario_output.get("entities", {})
        intent = scenario_output.get("intent", "")
        
        print(f"Single info collection - intent: {intent}, entities: {entities}")
        
        if entities and user_input:
            print(f"--- Verifying extracted entities: {entities} ---")
            verification_prompt_template = """
You are an exceptionally discerning assistant tasked with interpreting a user's intent. Your goal is to determine if the user has made a definitive choice or is simply asking a question about an option.

Here is the conversational context:
- The agent asked the user: "{agent_question}"
- The user replied: "{user_response}"
- From the user's reply, the following information was extracted: {entities}

Your task is to analyze the user's reply carefully. Has the user **committed** to the choice represented by the extracted information?

Consider these rules:
1.  **Direct questions are not commitments.** If the user asks "What is [option]?" or "Are there fees for [option]?", they have NOT committed.
2.  **Hypotheticals can be commitments.** If the user asks "If I choose [option], what happens next?", they ARE committing to that option for the sake of continuing the conversation.
3.  **Ambiguity means no commitment.** If it's unclear, err on the side of caution and decide it's not a commitment.

You MUST respond in JSON format with a single key "is_confirmed" (boolean). Example: {{"is_confirmed": true}}
"""
            verification_prompt = verification_prompt_template.format(
                agent_question=current_stage_info.get("prompt", ""),
                user_response=user_input,
                entities=str(entities)
            )
            
            try:
                response = await json_llm.ainvoke([HumanMessage(content=verification_prompt)])
                raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
                decision = json.loads(raw_content)
                is_confirmed = decision.get("is_confirmed", False)
                
                if is_confirmed:
                    print(f"--- Entity verification PASSED. Updating collected info. ---")
                    collected_info.update({k: v for k, v in entities.items() if v is not None})
                else:
                    print(f"--- Entity verification FAILED. Not updating collected info. ---")
            except Exception as e:
                print(f"Error during entity verification: {e}. Assuming not confirmed.")

        elif entities:
             collected_info.update({k: v for k, v in entities.items() if v is not None})

        print(f"Updated Info: {collected_info}")
    
    # 스테이지 전환 로직 결정
    transitions = current_stage_info.get("transitions", [])
    default_next = current_stage_info.get("default_next_stage_id", "None")
    
    # Case 1: 분기가 없는 경우 (transitions가 없거나 1개)
    if len(transitions) <= 1:
        # 필요한 정보가 수집되었는지 확인
        expected_info_key = current_stage_info.get("expected_info_key")
        if expected_info_key and expected_info_key not in collected_info:
            # 필요한 정보가 아직 수집되지 않았으면 현재 스테이지 유지
            next_stage_id = current_stage_id
            print(f"--- 자동 진행 차단: '{expected_info_key}' 정보 미수집 ---")
        elif len(transitions) == 1:
            # 단일 전환 경로가 있으면 자동 진행
            next_stage_id = transitions[0].get("next_stage_id", default_next)
            print(f"--- 자동 진행: 단일 경로 '{current_stage_id}' → '{next_stage_id}' ---")
        else:
            # transitions이 없으면 default로 진행
            next_stage_id = default_next
            print(f"--- 자동 진행: 기본 경로 '{current_stage_id}' → '{next_stage_id}' ---")
    
    # Case 2: 분기가 있는 경우 (transitions가 2개 이상) - LLM 판단
    else:
        print(f"--- LLM 판단 필요: {len(transitions)}개 분기 존재 ---")
        prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '')
        llm_prompt = prompt_template.format(
            active_scenario_name=active_scenario_data.get("scenario_name"),
            current_stage_id=str(current_stage_id),
            current_stage_prompt=current_stage_info.get("prompt", "No prompt"),
            user_input=state.get("stt_result", ""),
            scenario_agent_intent=scenario_output.get("intent", "N/A") if scenario_output else "N/A",
            scenario_agent_entities=str(scenario_output.get("entities", {}) if scenario_output else {}),
            collected_product_info=str(collected_info),
            formatted_transitions=format_transitions_for_prompt(transitions, current_stage_info.get("prompt", "")),
            default_next_stage_id=default_next
        )
        response = await json_llm.ainvoke([HumanMessage(content=llm_prompt)])
        decision_data = next_stage_decision_parser.parse(response.content)
        next_stage_id = decision_data.chosen_next_stage_id

    # --- 로직 전용 스테이지 처리 루프 ---
    while True:
        if not next_stage_id or str(next_stage_id).startswith("END"):
            break  # 종료 상태에 도달하면 루프 탈출

        next_stage_info = active_scenario_data.get("stages", {}).get(str(next_stage_id), {})
        
        # 스테이지에 `prompt`가 있으면 '말하는 스테이지'로 간주하고 루프 탈출
        if next_stage_info.get("prompt"):
            break
        
        # `prompt`가 없는 로직 전용 스테이지인 경우, 자동으로 다음 단계 진행
        print(f"--- Logic Stage Detected: '{next_stage_id}'. Resolving next step automatically. ---")
        
        current_stage_id_for_prompt = str(next_stage_id)
        
        # 로직 스테이지용 prompt_template 정의
        prompt_template = ALL_PROMPTS.get('main_agent', {}).get('determine_next_scenario_stage', '')
        llm_prompt = prompt_template.format(
            active_scenario_name=active_scenario_data.get("scenario_name"),
            current_stage_id=current_stage_id_for_prompt,
            current_stage_prompt=next_stage_info.get("prompt", "No prompt"),
            user_input="<NO_USER_INPUT_PROCEED_AUTOMATICALLY>", # 사용자 입력이 없음을 명시
            scenario_agent_intent="automatic_transition",
            scenario_agent_entities=str({}),
            collected_product_info=str(collected_info),
            formatted_transitions=format_transitions_for_prompt(next_stage_info.get("transitions", []), next_stage_info.get("prompt", "")),
            default_next_stage_id=next_stage_info.get("default_next_stage_id", "None")
        )
        response = await json_llm.ainvoke([HumanMessage(content=llm_prompt)])
        decision_data = next_stage_decision_parser.parse(response.content)
        
        next_stage_id = decision_data.chosen_next_stage_id # 다음 스테이지 ID를 갱신하고 루프 계속

    # 최종적으로 결정된 '말하는' 스테이지 ID
    determined_next_stage_id = next_stage_id
    
    updated_plan = state.get("action_plan", []).copy()
    if updated_plan:
        updated_plan.pop(0)
    
    updated_struct = state.get("action_plan_struct", []).copy()
    if updated_struct:
        updated_struct.pop(0)

    return {
        **state, 
        "collected_product_info": collected_info, 
        "current_scenario_stage_id": determined_next_stage_id,
        "action_plan": updated_plan,
        "action_plan_struct": updated_struct
    }

async def synthesize_response_node(state: AgentState) -> dict:
    has_factual = bool(state.get("factual_response"))
    has_contextual = bool(state.get("current_product_type"))
    has_direct = bool(state.get("main_agent_direct_response"))
    log_node_execution("Synthesizer", f"factual={has_factual}, contextual={has_contextual}, direct={has_direct}")
    
    # 1. 이미 final_response_text_for_tts가 설정되어 있으면 그것을 우선 사용
    existing_response = state.get("final_response_text_for_tts")
    if existing_response:
        print(f"이미 설정된 응답 사용: {existing_response}")
        updated_messages = list(state['messages']) + [AIMessage(content=existing_response)]
        return {"final_response_text_for_tts": existing_response, "messages": updated_messages, "is_final_turn_response": True}
    
    # 2. main_agent_direct_response가 있으면 우선 사용 (business_guidance에서 생성된 응답)
    direct_response = state.get("main_agent_direct_response")
    if direct_response:
        print(f"Main agent direct response 사용: {direct_response[:50]}...")
        updated_messages = list(state['messages']) + [AIMessage(content=direct_response)]
        return {"final_response_text_for_tts": direct_response, "messages": updated_messages, "is_final_turn_response": True}
    
    user_question = state["messages"][-1].content
    factual_answer = state.get("factual_response", "")
    
    contextual_response = ""
    active_scenario_data = get_active_scenario_data(state)
    if active_scenario_data:
        current_stage_id = state.get("current_scenario_stage_id")
        if current_stage_id and not str(current_stage_id).startswith("END_"):
             current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
             contextual_response = current_stage_info.get("prompt", "")
             if "%{" in contextual_response:
                import re
                if "end_scenario_message" in contextual_response:
                    contextual_response = re.sub(r'%\{end_scenario_message\}%', 
                        active_scenario_data.get("end_scenario_message", "상담이 완료되었습니다. 이용해주셔서 감사합니다."), 
                        contextual_response)
                else:
                    contextual_response = re.sub(r'%\{([^}]+)\}%', 
                        lambda m: str(state.get("collected_product_info", {}).get(m.group(1), f"")), 
                        contextual_response)
    
    if not factual_answer or "Could not find" in factual_answer:
        final_answer = contextual_response or "죄송합니다, 도움을 드리지 못했습니다."
    elif not contextual_response:
        final_answer = factual_answer
    else:
        try:
            response = await synthesizer_chain.ainvoke({
                "chat_history": state['messages'][:-1],
                "user_question": user_question,
                "contextual_response": f"After answering, you need to continue the conversation with this prompt: '{contextual_response}'",
                "factual_response": factual_answer,
            })
            final_answer = response.content.strip()
        except Exception as e:
            print(f"Synthesizer Error: {e}")
            final_answer = f"{factual_answer}\n\n{contextual_response}"

    # final_answer가 None이 되지 않도록 보장
    if not final_answer:
        final_answer = "죄송합니다, 응답을 생성하는데 문제가 발생했습니다."

    log_node_execution("Synthesizer", output_info=f"response='{final_answer[:40]}...'")
    updated_messages = list(state['messages']) + [AIMessage(content=final_answer)]
    
    return {"final_response_text_for_tts": final_answer, "messages": updated_messages, "is_final_turn_response": True}

async def end_conversation_node(state: AgentState) -> AgentState:
    log_node_execution("End_Conversation", "terminating session")
    response_text = "상담을 종료합니다. 이용해주셔서 감사합니다."
    
    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    return {
        **state, 
        "final_response_text_for_tts": response_text, 
        "messages": updated_messages, 
        "is_final_turn_response": True
    }

async def set_product_type_node(state: AgentState) -> AgentState:
    action_plan_struct = state.get("action_plan_struct", [])
    if action_plan_struct:
        product_id = action_plan_struct[0].get("tool_input", {}).get("product_id", "N/A")
        log_node_execution("Set_Product", f"product={product_id}")
    else:
        log_node_execution("Set_Product", "ERROR: no action plan")
    
    action_plan_struct = state.get("action_plan_struct", [])
    if not action_plan_struct:
        err_msg = "Action plan is empty in set_product_type_node"
        print(f"ERROR: {err_msg}")
        return {**state, "error_message": err_msg, "is_final_turn_response": True}
    
    # 현재 액션에 맞는 구조 찾기
    current_action_model = ActionModel.model_validate(action_plan_struct[0])
    
    new_product_type = current_action_model.tool_input.get("product_id")
    
    if not new_product_type:
        err_msg = f"product_id not found in action: {current_action_model.dict()}"
        print(f"ERROR: {err_msg}")
        return {**state, "error_message": err_msg, "is_final_turn_response": True}

    active_scenario = ALL_SCENARIOS_DATA.get(new_product_type)
    
    if not active_scenario:
        err_msg = f"Failed to load scenario for product type: {new_product_type}"
        print(f"ERROR: {err_msg}")
        return {**state, "error_message": err_msg, "is_final_turn_response": True}
        
    print(f"Successfully loaded scenario: {active_scenario.get('scenario_name')}")

    initial_stage_id = active_scenario.get("initial_stage_id")
    response_text = active_scenario.get("stages", {}).get(str(initial_stage_id), {}).get("prompt", "How can I help?")

    print(f"Generated response text: '{response_text[:70]}...'")

    updated_messages = list(state.get("messages", [])) + [AIMessage(content=response_text)]
    
    # 시나리오 연속성을 위한 상태 설정
    print(f"🔄 시나리오 연속성 준비: {active_scenario.get('scenario_name')}")
    
    return {
        **state, "current_product_type": new_product_type, "active_scenario_data": active_scenario,
        "active_scenario_name": active_scenario.get("scenario_name"), "current_scenario_stage_id": initial_stage_id,
        "collected_product_info": {}, "final_response_text_for_tts": response_text,
        "messages": updated_messages, "is_final_turn_response": True,
        # 시나리오 연속성 관리
        "scenario_ready_for_continuation": True,
        "scenario_awaiting_user_response": True
    }
    

def route_after_scenario_logic(state: AgentState) -> str:
    return "synthesize_response_node"

def execute_plan_router(state: AgentState) -> str:
    """간소화된 라우터 - Worker 중심 라우팅"""
    plan = state.get("action_plan", [])
    if not plan:
        log_node_execution("Router", "plan_complete → synthesizer")
        return "synthesize_response_node"

    next_action = plan[0] 
    target_node = None
    
    # Worker 중심 라우팅 맵
    worker_routing_map = {
        "invoke_scenario_agent": "scenario_worker",
        "invoke_qa_agent": "rag_worker", 
        "invoke_web_search": "web_worker",
        "set_product_type": "set_product_type_node",
        "end_conversation": "end_conversation_node"
    }
    target_node = worker_routing_map.get(next_action, "synthesize_response_node")
    log_node_execution("Router", f"{next_action} → {target_node.replace('_node', '').replace('_worker', '')}")
    return target_node

# --- Orchestration-Worker Graph Build ---
workflow = StateGraph(AgentState)

# Core Orchestrator
workflow.add_node("entry_point_node", entry_point_node)
workflow.add_node("main_agent_router_node", main_agent_router_node)

# Specialized Workers
workflow.add_node("scenario_worker", call_scenario_agent_node)
workflow.add_node("scenario_flow_worker", process_scenario_logic_node) 
workflow.add_node("rag_worker", factual_answer_node)
workflow.add_node("web_worker", web_search_node)

# Response & Control Nodes
workflow.add_node("synthesize_response_node", synthesize_response_node)
workflow.add_node("set_product_type_node", set_product_type_node)
workflow.add_node("end_conversation_node", end_conversation_node)

# Orchestrator Flow
workflow.set_entry_point("entry_point_node")
workflow.add_edge("entry_point_node", "main_agent_router_node")

# Orchestrator to Workers
workflow.add_conditional_edges(
    "main_agent_router_node",
    execute_plan_router,
    {
        "scenario_worker": "scenario_worker",
        "rag_worker": "rag_worker", 
        "web_worker": "web_worker",
        "synthesize_response_node": "synthesize_response_node",
        "set_product_type_node": "set_product_type_node",
        "end_conversation_node": "end_conversation_node",
    }
)

# Worker Flows
workflow.add_edge("scenario_worker", "scenario_flow_worker")
workflow.add_conditional_edges("scenario_flow_worker", execute_plan_router)
workflow.add_conditional_edges("rag_worker", execute_plan_router)
workflow.add_conditional_edges("web_worker", execute_plan_router)

workflow.add_edge("synthesize_response_node", END)
workflow.add_edge("set_product_type_node", END)
workflow.add_edge("end_conversation_node", END)

app_graph = workflow.compile()
print("--- LangGraph compiled successfully (Orchestration-Worker Architecture). ---")

async def run_agent_streaming(
    user_input_text: Optional[str] = None,
    user_input_audio_b64: Optional[str] = None,
    session_id: Optional[str] = "default_session",
    current_state_dict: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Union[Dict[str, Any], str], None]:
    
    if not OPENAI_API_KEY or not json_llm or not generative_llm:
        error_msg = "LLM service is not initialized. Please check API key."
        yield {"type": "error", "message": error_msg}
        yield {"type": "final_state", "data": {"error_message": error_msg, "is_final_turn_response": True}}
        return

    initial_state = cast(AgentState, {
        "session_id": session_id or "default_session",
        "user_input_text": user_input_text,
        "user_input_audio_b64": user_input_audio_b64,
        "messages": current_state_dict.get("messages", []) if current_state_dict else [],
        "current_product_type": current_state_dict.get("current_product_type") if current_state_dict else None,
        "current_scenario_stage_id": current_state_dict.get("current_scenario_stage_id") if current_state_dict else None,
        "collected_product_info": current_state_dict.get("collected_product_info", {}) if current_state_dict else {},
        "available_product_types": ["didimdol", "jeonse", "deposit_account"],
        "action_plan": [],
        "action_plan_struct": [],
        # 시나리오 연속성 상태 복원
        "scenario_ready_for_continuation": current_state_dict.get("scenario_ready_for_continuation", False) if current_state_dict else False,
        "scenario_awaiting_user_response": current_state_dict.get("scenario_awaiting_user_response", False) if current_state_dict else False,
    })

    print(f"\n🚀 ===== AGENT FLOW START [{session_id}] =====")
    log_node_execution("Session", f"product={initial_state['current_product_type']}, input='{user_input_text[:30]}...'")

    final_state: Optional[AgentState] = None
    streamed_text = ""

    try:
        final_state = await app_graph.ainvoke(initial_state)
        
        if final_state and final_state.get("final_response_text_for_tts"):
            text_to_stream = final_state["final_response_text_for_tts"]
            yield {"type": "stream_start"}
            for char in text_to_stream:
                yield char
                streamed_text += char
                await asyncio.sleep(0.01)
            yield {"type": "stream_end", "full_text": streamed_text}
        else:
            error_msg = final_state.get("error_message", "Failed to generate a response.")
            yield {"type": "error", "message": error_msg}
            if final_state: final_state["final_response_text_for_tts"] = error_msg

    except Exception as e:
        print(f"CRITICAL error in run_agent_streaming for session {session_id}: {e}")
        traceback.print_exc()
        error_response = "A critical system error occurred during processing."
        yield {"type": "error", "message": error_response}
        final_state = cast(AgentState, initial_state.copy())
        final_state["error_message"] = error_response
        final_state["is_final_turn_response"] = True
        final_state["messages"] = list(initial_state.get("messages", [])) + [AIMessage(content=error_response)]
    
    finally:
        if final_state:
            yield {"type": "final_state", "data": final_state}
        else:
            final_state = initial_state
            final_state["error_message"] = "Agent execution failed critically, no final state produced."
            final_state["is_final_turn_response"] = True
            yield {"type": "final_state", "data": final_state}
        print(f"🏁 ===== AGENT FLOW END [{session_id}] =====")