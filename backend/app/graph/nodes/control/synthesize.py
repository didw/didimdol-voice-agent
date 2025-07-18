# backend/app/graph/nodes/control/synthesize.py
"""
응답 합성 노드 - Worker 응답들을 통합하여 최종 응답 생성
"""
import re
import json
from typing import Dict, Any, Optional
from langchain_core.messages import AIMessage

from ...state import AgentState
from ...utils import get_active_scenario_data
from ...chains import synthesizer_chain
from ...logger import node_log as log_node_execution, log_execution_time


@log_execution_time
async def synthesize_response_node(state: AgentState) -> AgentState:
    """
    응답 합성 노드
    - direct message + no worker → 바로 출력
    - 그 외 모든 경우 → synthesizer agent 처리
    """
    # 응답 생성 헬퍼 함수
    def create_response(response_text: str, log_msg: str = "response") -> AgentState:
        log_node_execution("Synthesizer", f"{log_msg}: {response_text[:50]}...")
        updated_messages = list(state.messages) + [AIMessage(content=response_text)]
        state_updates = {
            "final_response_text_for_tts": response_text,
            "messages": updated_messages,
            "is_final_turn_response": True
        }
        return state.merge_update(state_updates)
    
    # 1. 이미 설정된 최종 응답이 있으면 반환
    if state.final_response_text_for_tts:
        return create_response(state.final_response_text_for_tts, "existing response")
    
    # 2. Direct message가 있고 Worker 호출이 없는 경우 → 바로 출력
    has_direct_message = bool(state.main_agent_direct_response)
    has_worker_plan = bool(state.action_plan)
    
    if has_direct_message and not has_worker_plan:
        log_node_execution("Synthesizer", "Direct message with no workers - quick return")
        return create_response(state.main_agent_direct_response, "direct response (no synthesis)")
    
    # 3. 그 외 모든 경우 → Synthesizer Agent에서 응답 생성
    log_node_execution("Synthesizer", "Synthesizer agent processing required")
    
    # 분석 컨텍스트 생성
    analysis_context = format_analysis_context(state)
    
    try:
        # Synthesizer chain 호출
        response = await synthesizer_chain.ainvoke({
            "user_question": state.stt_result or "",
            "analysis_context": analysis_context
        })
        
        final_answer = response.content.strip()
        
        # 응답이 비어있는 경우 처리
        if not final_answer:
            final_answer = generate_fallback_response(state)
        
        return create_response(final_answer, "synthesized response")
        
    except Exception as e:
        log_node_execution("Synthesizer", f"ERROR during synthesis: {e}")
        # 에러 시 폴백 응답 생성
        fallback = generate_fallback_response(state)
        return create_response(fallback, "error fallback")


def format_analysis_context(state: AgentState) -> str:
    """
    Synthesizer를 위한 분석 컨텍스트 생성
    - Direct message 여부와 관계없이 모든 정보 포함
    """
    context_parts = []
    
    # 1. 현재 상황
    if state.current_scenario_stage_id:
        context_parts.append(f"## 시나리오 진행 상황")
        context_parts.append(f"- 현재 시나리오: {state.active_scenario_name}")
        context_parts.append(f"- 현재 단계: {state.current_scenario_stage_id}")
        
        stage_info = get_current_stage_info(state)
        if stage_info and stage_info.get("expected_info_key"):
            info_key = stage_info["expected_info_key"]
            collected = state.collected_product_info.get(info_key) is not None
            context_parts.append(f"- 필요한 정보: {info_key} (수집 여부: {'완료' if collected else '미완료'})")
    else:
        context_parts.append("## 가능한 서비스")
        context_parts.append("- 디딤돌 대출 상담")
        context_parts.append("- 전세 대출 상담")
        context_parts.append("- 입출금통장 신규")
    
    # 2. Orchestrator의 Direct Message (있는 경우)
    if state.main_agent_direct_response:
        context_parts.append("\n## Orchestrator 제안")
        context_parts.append(state.main_agent_direct_response)
    
    # 3. Worker 분석 결과
    context_parts.append("\n## Worker 분석 결과")
    
    worker_count = 0
    
    # Scenario Worker 응답
    if state.scenario_agent_output:
        worker_count += 1
        context_parts.append(f"\n### {worker_count}. 시나리오 분석")
        context_parts.append(f"- 의도: {state.scenario_agent_output.intent}")
        if state.scenario_agent_output.entities:
            context_parts.append(f"- 추출된 정보: {json.dumps(state.scenario_agent_output.entities, ensure_ascii=False)}")
        context_parts.append(f"- 시나리오 관련성: {'관련됨' if state.scenario_agent_output.is_scenario_related else '관련없음'}")
    
    # RAG Worker 응답
    if state.factual_response:
        worker_count += 1
        context_parts.append(f"\n### {worker_count}. 지식 기반 검색 결과")
        context_parts.append(state.factual_response)
    
    # Web Worker 응답 (있다면)
    if hasattr(state, 'web_search_response') and state.web_search_response:
        worker_count += 1
        context_parts.append(f"\n### {worker_count}. 웹 검색 결과")
        context_parts.append(state.web_search_response)
    
    # Worker가 하나도 없는 경우
    if worker_count == 0:
        context_parts.append("(Worker 호출 없음)")
    
    # 4. 수집된 정보 요약
    if state.current_scenario_stage_id and state.collected_product_info:
        context_parts.append("\n## 현재까지 수집된 정보")
        for key, value in state.collected_product_info.items():
            context_parts.append(f"- {key}: {value}")
    
    return "\n".join(context_parts)


def get_current_stage_info(state: AgentState) -> Optional[Dict[str, Any]]:
    """현재 시나리오 단계 정보 가져오기"""
    active_scenario_data = get_active_scenario_data(state.to_dict())
    if not active_scenario_data or not state.current_scenario_stage_id:
        return None
    
    return active_scenario_data.get("stages", {}).get(str(state.current_scenario_stage_id), {})


def get_current_stage_prompt_with_variables(state: AgentState) -> Optional[str]:
    """현재 시나리오 단계의 프롬프트를 변수 치환하여 반환"""
    stage_info = get_current_stage_info(state)
    if not stage_info or not stage_info.get("prompt"):
        return None
    
    return process_prompt_variables(
        stage_info["prompt"], 
        state.collected_product_info,
        state
    )


def process_prompt_variables(prompt: str, collected_info: Dict[str, Any], state: AgentState) -> str:
    """프롬프트 내 변수를 실제 값으로 치환"""
    if "%{" in prompt:
        if "end_scenario_message" in prompt:
            active_scenario_data = get_active_scenario_data(state.to_dict())
            end_message = active_scenario_data.get("end_scenario_message", "상담이 완료되었습니다. 이용해주셔서 감사합니다.") if active_scenario_data else "상담이 완료되었습니다. 이용해주셔서 감사합니다."
            prompt = re.sub(
                r'%\{end_scenario_message\}%', 
                end_message, 
                prompt
            )
        else:
            prompt = re.sub(
                r'%\{([^}]+)\}%', 
                lambda m: str(collected_info.get(m.group(1), "")), 
                prompt
            )
    
    return prompt


def generate_fallback_response(state: AgentState) -> str:
    """응답 생성 실패 시 폴백 응답 생성"""
    # 우선순위: factual > direct > scenario prompt > default
    if state.factual_response:
        return state.factual_response
    elif state.main_agent_direct_response:
        return state.main_agent_direct_response
    elif state.current_scenario_stage_id:
        prompt = get_current_stage_prompt_with_variables(state)
        if prompt:
            return prompt
    
    return "죄송합니다, 무엇을 도와드릴까요?"