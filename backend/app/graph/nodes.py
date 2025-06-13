# backend/app/graph/nodes.py

import json
import traceback
from typing import Dict, Any, cast, List

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from .state import AgentState, ScenarioAgentOutput
from .prompts import (
    ALL_PROMPTS, ALL_SCENARIOS_DATA, json_llm, generative_llm,
    format_messages_for_prompt, format_transitions_for_prompt,
    load_knowledge_base_content_async
)
from .parsers import (
    scenario_output_parser,
    next_stage_decision_parser,
    main_router_decision_parser,
    initial_task_decision_parser
)

# --- Node Implementations ---

async def entry_point_node(state: AgentState) -> AgentState:
    """Graph의 진입점으로, 매 턴마다 상태를 초기화하고 사용자 입력을 메시지 목록에 추가합니다."""
    print("--- 노드: Entry Point ---")
    if not ALL_SCENARIOS_DATA or not ALL_PROMPTS:
        error_msg = "상담 서비스 초기화 실패 (시나리오 또는 프롬프트 데이터 로드 불가)."
        print(f"CRITICAL: 필수 데이터가 로드되지 않았습니다.")
        return {**state, "error_message": error_msg, "final_response_text_for_tts": error_msg, "is_final_turn_response": True}

    # 현재 턴에서만 사용되는 상태 값들을 초기화합니다.
    turn_specific_defaults: Dict[str, Any] = {
        "main_agent_routing_decision": None,
        "main_agent_direct_response": None,
        "scenario_agent_output": None,
        "final_response_text_for_tts": None,
        "is_final_turn_response": False,
        "error_message": None,
        "factual_response": None,
    }
    updated_state = {**state, **turn_specific_defaults}

    # 사용자 입력을 메시지 리스트에 추가합니다.
    user_text_for_turn = state.get("stt_result") or state.get("user_input_text")
    if user_text_for_turn:
        current_messages = list(updated_state.get("messages", []))
        # 중복 추가 방지
        if not current_messages or not (isinstance(current_messages[-1], HumanMessage) and current_messages[-1].content == user_text_for_turn):
            current_messages.append(HumanMessage(content=user_text_for_turn))
        updated_state["messages"] = current_messages
    
    return cast(AgentState, updated_state)


async def main_agent_router_node(state: AgentState) -> AgentState:
    """사용자 입력과 현재 상태를 기반으로 어떤 노드를 실행할지 결정하는 메인 분기 노드입니다."""
    print("--- 노드: Main Agent Router ---")
    if not json_llm:
        return {**state, "error_message": "라우터 서비스 사용 불가 (LLM 미초기화)", "final_response_text_for_tts": "시스템 설정 오류입니다.", "is_final_turn_response": True}
 
    user_input = state.get("stt_result", "")
    current_product_type = state.get("current_product_type")
    
    # 상담 상품이 정해지지 않은 경우와 정해진 경우, 다른 프롬프트를 사용합니다.
    prompt_template_key = 'initial_task_selection_prompt' if not current_product_type else 'router_prompt'
    prompt_template = ALL_PROMPTS.get('main_agent', {}).get(prompt_template_key, '')

    if not prompt_template:
        return {**state, "error_message": "라우터 프롬프트 로드 실패", "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}

    try:
        # 사용할 파서(JSON 형식 정의)를 선택합니다.
        response_parser = initial_task_decision_parser if not current_product_type else main_router_decision_parser
        format_instructions = response_parser.get_format_instructions()
        
        # 프롬프트에 필요한 정보를 채워넣습니다.
        if not current_product_type:
             # 첫 대화일 경우, 간단한 프롬프트를 사용합니다.
             main_agent_prompt_filled = prompt_template.format(user_input=user_input, format_instructions=format_instructions)
        else:
             # 상담이 진행 중일 경우, 더 많은 컨텍스트 정보를 제공합니다.
            messages_history = state.get("messages", [])
            history_for_prompt = list(messages_history[:-1]) if messages_history and isinstance(messages_history[-1], HumanMessage) else list(messages_history)
            formatted_history_str = format_messages_for_prompt(history_for_prompt)
            active_scenario_data = ALL_SCENARIOS_DATA.get(current_product_type, {})
            current_stage_id_for_prompt = state.get("current_scenario_stage_id", active_scenario_data.get("initial_stage_id", "정보 없음"))
            current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id_for_prompt), {})

            main_agent_prompt_filled = prompt_template.format(
                user_input=user_input,
                active_scenario_name=active_scenario_data.get("scenario_name", "미정"),
                formatted_messages_history=formatted_history_str,
                current_scenario_stage_id=current_stage_id_for_prompt,
                current_stage_prompt=current_stage_info.get("prompt", "안내 없음"),
                collected_product_info=str(state.get("collected_product_info", {})),
                expected_info_key=current_stage_info.get("expected_info_key", "정보 없음"),
                available_product_types_display=", ".join([scen["scenario_name"] for scen in ALL_SCENARIOS_DATA.values()]),
                format_instructions=format_instructions
            )

        # LLM을 호출하여 라우팅 결정을 받습니다.
        response = await json_llm.ainvoke([HumanMessage(content=main_agent_prompt_filled)])
        raw_response_content = response.content.strip()
        parsed_decision = response_parser.parse(raw_response_content)
        
        # 결정된 내용을 상태에 저장합니다.
        new_state_changes: Dict[str, Any] = {"main_agent_routing_decision": parsed_decision.action}
        if hasattr(parsed_decision, 'direct_response') and parsed_decision.direct_response:
            new_state_changes["main_agent_direct_response"] = parsed_decision.direct_response
        
        # 시스템 메시지로 라우팅 결정을 기록합니다. (디버깅 및 컨텍스트 유지용)
        system_log_message = f"Main Agent 판단 결과: action='{parsed_decision.action}'"
        updated_messages = list(state.get("messages", [])) + [SystemMessage(content=system_log_message)]
        new_state_changes["messages"] = updated_messages

        # 첫 대화의 경우, 결정에 따라 상품 타입을 설정합니다.
        if not current_product_type:
            initial_decision = cast(initial_task_decision_parser.pydantic_object, parsed_decision)
            if initial_decision.action.startswith("proceed_with_product_type_"):
                product = initial_decision.action.replace("proceed_with_product_type_", "")
                new_state_changes["main_agent_routing_decision"] = f"set_product_type_{product}"
            elif initial_decision.action == "invoke_qa_agent_general":
                new_state_changes["main_agent_routing_decision"] = "invoke_qa_agent"
            elif initial_decision.action == "clarify_product_type":
                new_state_changes["main_agent_routing_decision"] = "select_product_type"
            elif initial_decision.action == "answer_directly_chit_chat":
                new_state_changes["main_agent_routing_decision"] = "answer_directly_chit_chat"

        return {**state, **new_state_changes}

    except Exception as e:
        print(f"Main Agent Router 시스템 오류: {e}")
        traceback.print_exc()
        err_msg = "요청 처리 중 시스템 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        return {**state, "error_message": err_msg, "final_response_text_for_tts": err_msg, "main_agent_routing_decision": "unclear_input", "is_final_turn_response": True}


async def set_product_type_node(state: AgentState) -> AgentState:
    """상담할 상품 타입을 상태(state)에 설정하고, 사용자에게 안내 메시지를 생성합니다."""
    print(f"--- 노드: 상품 유형 설정 ---")
    decision = state.get("main_agent_routing_decision")
    # decision 형식: "set_product_type_didimdol"
    product_type = decision.replace("set_product_type_", "")
    
    if product_type not in ALL_SCENARIOS_DATA:
        err_msg = f"'{product_type}'은(는) 유효하지 않은 상품 유형입니다."
        return {**state, "error_message": err_msg, "final_response_text_for_tts": err_msg, "is_final_turn_response": True}

    active_scenario = ALL_SCENARIOS_DATA[product_type]
    scenario_name = active_scenario.get("scenario_name", "해당 상품")
    initial_stage_id = active_scenario.get("initial_stage_id")
    initial_stage_info = active_scenario.get("stages", {}).get(initial_stage_id, {})
    initial_prompt = initial_stage_info.get("prompt")

    if not initial_stage_id or not initial_prompt:
        err_msg = f"{scenario_name} 상담을 시작할 수 없습니다. (초기 단계 정보 부족)"
        return {**state, "error_message": err_msg, "final_response_text_for_tts": err_msg, "is_final_turn_response": True}

    response_text = f"네, {scenario_name}에 대해 안내해 드리겠습니다. {initial_prompt}"
    
    updated_messages = list(state.get("messages", []))
    updated_messages.append(AIMessage(content=response_text))

    return {
        **state,
        "current_product_type": product_type,
        "current_scenario_stage_id": initial_stage_id,
        "collected_product_info": {},  # 상품이 바뀌었으므로 초기화
        "final_response_text_for_tts": response_text,
        "messages": updated_messages,
        "is_final_turn_response": True, # 최종 응답 설정
    }


async def call_scenario_agent_node(state: AgentState) -> AgentState:
    """시나리오 에이전트를 호출하여 사용자 발화의 의도와 개체를 분석합니다."""
    print("--- 노드: Scenario Agent 호출 ---")
    user_input = state.get("stt_result", "")
    current_product_type = state.get("current_product_type")

    if not json_llm or not current_product_type or not user_input:
        error_output = cast(ScenarioAgentOutput, {"intent": "error_missing_data", "entities": {}, "is_scenario_related": False})
        return {**state, "scenario_agent_output": error_output}

    active_scenario_data = ALL_SCENARIOS_DATA.get(current_product_type, {})
    current_stage_id = state.get("current_scenario_stage_id") or active_scenario_data.get("initial_stage_id")
    current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})

    # LLM 호출 로직을 별도 함수로 분리하여 호출
    output = await _invoke_scenario_agent_llm(
        user_input=user_input,
        current_stage_prompt=current_stage_info.get("prompt", ""),
        expected_info_key=current_stage_info.get("expected_info_key"),
        messages_history=state.get("messages", [])[:-1], # 마지막 사용자 입력 제외
        scenario_name=active_scenario_data.get("scenario_name", "대출 상담")
    )
    return {**state, "scenario_agent_output": output}

async def _invoke_scenario_agent_llm(user_input: str, current_stage_prompt: str, expected_info_key: str | None, messages_history: list, scenario_name: str) -> ScenarioAgentOutput:
    """Scenario Agent의 실제 LLM 호출을 담당하는 내부 함수입니다."""
    try:
        scenario_agent_prompt_template = ALL_PROMPTS.get('scenario_agent', {}).get('main_prompt', '')
        if not scenario_agent_prompt_template:
            raise ValueError("Scenario agent main prompt not found")

        format_instructions = scenario_output_parser.get_format_instructions()
        formatted_history = format_messages_for_prompt(messages_history)

        prompt_filled = scenario_agent_prompt_template.format(
            user_input=user_input,
            scenario_name=scenario_name,
            current_stage_prompt=current_stage_prompt,
            expected_info_key=str(expected_info_key),
            formatted_messages_history=formatted_history,
            format_instructions=format_instructions
        )
        
        response = await json_llm.ainvoke([HumanMessage(content=prompt_filled)])
        parsed_output = scenario_output_parser.parse(response.content.strip())
        
        return cast(ScenarioAgentOutput, parsed_output.dict())
    except Exception as e:
        print(f"Scenario Agent LLM 호출 오류: {e}")
        return cast(ScenarioAgentOutput, {"intent": f"error_parsing_failed: {e}", "entities": {}, "is_scenario_related": False})


async def main_agent_scenario_processing_node(state: AgentState) -> AgentState:
    """Scenario Agent의 분석 결과를 바탕으로 다음 단계를 결정하고 응답을 생성합니다."""
    print("--- 노드: Main Agent 시나리오 처리 ---")
    if not json_llm:
        return {**state, "error_message": "시나리오 처리 서비스 사용 불가", "final_response_text_for_tts": "시스템 설정 오류입니다.", "is_final_turn_response": True}

    scenario_output = state.get("scenario_agent_output")
    if not scenario_output:
        return {**state, "final_response_text_for_tts": "분석 결과가 없습니다.", "is_final_turn_response": True}

    # 1. 추출된 정보(entities)를 상태에 저장
    collected_info = state.get("collected_product_info", {})
    extracted_entities = scenario_output.get("entities", {})
    if extracted_entities:
        collected_info.update(extracted_entities)
    
    # 2. 다음 시나리오 단계 결정
    current_product_type = state.get("current_product_type")
    active_scenario = ALL_SCENARIOS_DATA.get(current_product_type, {})
    current_stage_id = state.get("current_scenario_stage_id")
    current_stage_info = active_scenario.get("stages", {}).get(str(current_stage_id), {})
    transitions = current_stage_info.get("transitions", [])
    
    # LLM을 통해 다음 단계 결정
    next_stage_id = await _decide_next_stage_with_llm(
        user_input=state.get("stt_result", ""),
        scenario_output=scenario_output,
        transitions=transitions,
        current_stage_prompt=current_stage_info.get("prompt", ""),
        collected_info=collected_info
    )

    # 3. 최종 응답 생성 및 상태 업데이트
    next_stage_info = active_scenario.get("stages", {}).get(str(next_stage_id), {})
    response_text = next_stage_info.get("prompt", "다음 질문으로 넘어가겠습니다.")
    
    updated_messages = list(state.get("messages", []))
    # 시나리오 처리 결과를 시스템 메시지로 기록
    log_msg = f"시나리오 처리: '{scenario_output.get('intent')}' 감지 -> 다음 단계 '{next_stage_id}'로 이동."
    updated_messages.append(SystemMessage(content=log_msg))
    updated_messages.append(AIMessage(content=response_text))
    
    return {
        **state,
        "collected_product_info": collected_info,
        "current_scenario_stage_id": next_stage_id,
        "messages": updated_messages,
        "final_response_text_for_tts": response_text,
        "is_final_turn_response": True
    }

async def _decide_next_stage_with_llm(user_input: str, scenario_output: dict, transitions: List[Dict], current_stage_prompt: str, collected_info: dict) -> str:
    """LLM을 사용하여 현재 상태와 사용자 입력을 바탕으로 최적의 다음 단계를 결정합니다."""
    # 만약 전환 규칙이 하나뿐이면 바로 그 단계를 반환
    if len(transitions) == 1:
        return transitions[0]['next_stage_id']
    if not transitions:
        return "END" # 전환 규칙이 없으면 종료

    try:
        decision_prompt_template = ALL_PROMPTS.get('main_agent', {}).get('next_stage_decision_prompt', '')
        if not decision_prompt_template:
            raise ValueError("Next stage decision prompt not found")

        format_instructions = next_stage_decision_parser.get_format_instructions()
        formatted_transitions = format_transitions_for_prompt(transitions, current_stage_prompt)
        
        prompt_filled = decision_prompt_template.format(
            user_input=user_input,
            scenario_agent_output_str=json.dumps(scenario_output, ensure_ascii=False),
            formatted_transitions=formatted_transitions,
            collected_info_str=json.dumps(collected_info, ensure_ascii=False),
            format_instructions=format_instructions
        )

        response = await json_llm.ainvoke([HumanMessage(content=prompt_filled)])
        parsed_decision = next_stage_decision_parser.parse(response.content.strip())
        
        # 결정된 ID가 유효한지 확인
        valid_next_stage_ids = {t['next_stage_id'] for t in transitions}
        if parsed_decision.chosen_next_stage_id in valid_next_stage_ids:
            return parsed_decision.chosen_next_stage_id
        else:
            print(f"경고: LLM이 유효하지 않은 다음 단계({parsed_decision.chosen_next_stage_id})를 선택했습니다. 기본값으로 이동합니다.")
            return transitions[0]['next_stage_id'] # 기본값으로 첫 번째 전환 사용

    except Exception as e:
        print(f"다음 단계 결정 중 오류 발생: {e}. 기본 전환 규칙을 따릅니다.")
        return transitions[0]['next_stage_id'] if transitions else "END"


async def factual_answer_node(state: AgentState) -> dict:
    """지식 베이스(KB)를 참조하여 사실 기반 질문에 답변하는 노드입니다."""
    print("--- 노드: Factual Answer (QA Agent) ---")
    user_question = state.get("stt_result", "")
    # QA는 현재 상품 컨텍스트를 따르거나, 컨텍스트가 없으면 일반 QA로 동작
    qa_context_product_type = state.get("current_product_type")
    
    if not generative_llm:
         return {"factual_response": "답변 생성 서비스를 사용할 수 없습니다."}

    try:
        # 해당 상품의 지식베이스(KB) 내용을 비동기적으로 로드
        kb_content = await load_knowledge_base_content_async(qa_context_product_type) if qa_context_product_type else None
        
        if not kb_content or kb_content in ["NOT_AVAILABLE", "ERROR_LOADING_FAILED"]:
            kb_for_prompt = "현재 참고할 수 있는 구체적인 상품 정보가 없습니다."
            scenario_name_for_prompt = "일반 금융"
        else:
            kb_for_prompt = kb_content
            scenario_name_for_prompt = ALL_SCENARIOS_DATA.get(qa_context_product_type, {}).get("scenario_name", "해당 상품")
            
        qa_prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('main_prompt', '')
        if not qa_prompt_template:
            raise ValueError("QA agent main prompt not found")

        prompt_filled = qa_prompt_template.format(
            user_question=user_question,
            knowledge_base=kb_for_prompt,
            scenario_name=scenario_name_for_prompt
        )

        response_chunks = []
        async for chunk in generative_llm.astream([HumanMessage(content=prompt_filled)]):
            response_chunks.append(chunk.content)
        
        factual_response = "".join(response_chunks)
        return {"factual_response": factual_response}

    except Exception as e:
        print(f"Factual Answer Node 실행 중 오류 발생: {e}")
        return {"factual_response": "정보를 찾는 중 시스템 오류가 발생했습니다."}


async def synthesize_answer_node(state: AgentState) -> dict:
    """여러 소스(예: QA 결과)를 종합하여 최종 사용자 응답을 자연스럽게 가다듬습니다."""
    print("--- 노드: Synthesize Answer ---")
    factual_response = state.get("factual_response", "답변을 생성하지 못했습니다.")
    
    # 현재는 QA 결과를 바로 사용하지만, 향후 여러 정보를 종합하는 로직 추가 가능
    final_text = factual_response
    
    updated_messages = list(state.get("messages", []))
    updated_messages.append(AIMessage(content=final_text))
    
    return {
        "messages": updated_messages,
        "final_response_text_for_tts": final_text,
        "is_final_turn_response": True
    }


async def prepare_direct_response_node(state: AgentState) -> AgentState:
    """Main Agent가 직접 생성한 답변(예: 잡담)을 최종 응답으로 설정합니다."""
    print("--- 노드: 직접 응답 준비 ---")
    direct_response = state.get("main_agent_direct_response", "네, 알겠습니다.")
    updated_messages = list(state.get("messages", []))
    updated_messages.append(AIMessage(content=direct_response))
    
    return {
        **state,
        "messages": updated_messages,
        "final_response_text_for_tts": direct_response,
        "is_final_turn_response": True
    }


async def prepare_fallback_response_node(state: AgentState) -> AgentState:
    """어떤 노드도 요청을 처리할 수 없을 때, 기본 응답을 생성합니다."""
    print("--- 노드: 폴백 응답 준비 ---")
    fallback_text = "죄송합니다, 잘 이해하지 못했습니다. 다시 한번 말씀해주시겠어요?"
    updated_messages = list(state.get("messages", []))
    updated_messages.append(AIMessage(content=fallback_text))

    return {
        **state,
        "messages": updated_messages,
        "final_response_text_for_tts": fallback_text,
        "is_final_turn_response": True
    }


async def prepare_end_conversation_node(state: AgentState) -> AgentState:
    """대화 종료 응답을 생성합니다."""
    print("--- 노드: 대화 종료 메시지 준비 ---")
    end_text = state.get("main_agent_direct_response") or "네, 알겠습니다. 상담을 종료합니다. 이용해주셔서 감사합니다."
    updated_messages = list(state.get("messages", []))
    updated_messages.append(AIMessage(content=end_text))

    return {
        **state,
        "messages": updated_messages,
        "final_response_text_for_tts": end_text,
        "is_final_turn_response": True
    }


async def handle_error_node(state: AgentState) -> AgentState:
    """오류 발생 시, 사용자에게 안내할 메시지를 설정합니다."""
    print("--- 노드: 에러 핸들링 ---")
    error_message = state.get("error_message", "죄송합니다. 처리 중 오류가 발생했습니다.")
    updated_messages = list(state.get("messages", []))
    updated_messages.append(AIMessage(content=error_message))

    return {
        **state,
        "messages": updated_messages,
        "final_response_text_for_tts": error_message,
        "is_final_turn_response": True
    }