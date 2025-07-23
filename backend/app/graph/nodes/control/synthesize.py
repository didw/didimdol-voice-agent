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
    
    # 디버그 로그 추가
    print(f"[Synthesizer] ===== START =====")
    print(f"[Synthesizer] Incoming final_response_text_for_tts: '{state.final_response_text_for_tts}'")
    print(f"[Synthesizer] Incoming is_final_turn_response: {state.is_final_turn_response}")
    print(f"[Synthesizer] Incoming action_plan: {state.action_plan}")
    
    # 1. 이미 설정된 최종 응답이 있으면 반환
    if state.final_response_text_for_tts:
        print(f"[Synthesizer] Using existing final_response_text_for_tts: '{state.final_response_text_for_tts}'")
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
            "chat_history": list(state.messages),
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
    - 시나리오 정보를 체계적으로 정리
    """
    context_parts = []
    
    # 1. 시나리오 진행 상황
    if state.current_scenario_stage_id:
        active_scenario_data = get_active_scenario_data(state.to_dict())
        
        context_parts.append("## 1. 시나리오 개요")
        context_parts.append(f"### 현재 시나리오: {state.active_scenario_name}")
        if active_scenario_data:
            context_parts.append(f"- 목적: {active_scenario_data.get('system_prompt', '금융 상담 진행')}")
        
        # 2. 진행 단계 정보
        context_parts.append("\n## 2. 진행 단계")
        stage_info = get_current_stage_info(state)
        
        # 전체 단계 수 계산 (간단히 stages 키 개수로)
        total_stages = len(active_scenario_data.get("stages", {})) if active_scenario_data else 0
        context_parts.append(f"- 전체 단계: 약 {total_stages}개")
        context_parts.append(f"- 현재 단계: {state.current_scenario_stage_id}")
        
        # END_SCENARIO 또는 complete_application 같은 종료 단계 표시
        if state.current_scenario_stage_id in ["complete_application", "END_SCENARIO", "info_correction_end"]:
            context_parts.append("- **[종료 단계]** 이 단계는 시나리오의 마지막 단계입니다. 다음 단계 안내를 추가하지 마세요.")
        
        if stage_info:
            current_prompt = stage_info.get("prompt", "")
            if current_prompt:
                # 변수가 치환된 프롬프트 보여주기
                processed_prompt = process_prompt_variables(current_prompt, state.collected_product_info, state)
                context_parts.append(f"- 현재 질문/안내: {processed_prompt}")
        
        # 3. 필드 수집 상황
        context_parts.append("\n## 3. 정보 수집 현황")
        field_status = analyze_field_status(state, active_scenario_data)
        
        context_parts.append(f"### 전체 필드 상태")
        context_parts.append(f"- 총 필수 필드: {field_status['total_required']}")
        context_parts.append(f"- 수집 완료: {field_status['collected']}")
        context_parts.append(f"- 수집 필요: {field_status['remaining']}")
        
        if field_status['current_stage_fields']:
            context_parts.append(f"\n### 현재 단계 관련 필드")
            for field in field_status['current_stage_fields']:
                status = "✅ 수집됨" if field['collected'] else "⏳ 대기중"
                value = f" = {field['value']}" if field['collected'] else ""
                context_parts.append(f"- {field['key']} ({field['display_name']}): {status}{value}")
    else:
        context_parts.append("## 가능한 서비스")
        context_parts.append("- 디딤돌 대출 상담")
        context_parts.append("- 전세 대출 상담")
        context_parts.append("- 입출금통장 신규")
    
    # 2. Orchestrator의 Direct Message (있는 경우)
    if state.main_agent_direct_response:
        context_parts.append("\n## Orchestrator 제안")
        context_parts.append(state.main_agent_direct_response)
    
    # 4. Worker 분석 결과 (이번 턴에 실행된 경우만)
    context_parts.append("\n## 4. Worker 분석 결과")
    
    worker_count = 0
    
    # Scenario Worker 응답
    if state.scenario_agent_output:
        worker_count += 1
        context_parts.append(f"\n### {worker_count}. 시나리오 분석")
        context_parts.append(f"- 사용자 의도: {state.scenario_agent_output.intent}")
        
        if state.scenario_agent_output.entities:
            context_parts.append(f"- 추출된 정보:")
            # stage_info가 이미 위에서 정의됨
            expected_key = stage_info.get("expected_info_key") if stage_info else None
            for key, value in state.scenario_agent_output.entities.items():
                # 현재 단계에서 기대하는 필드인지 표시
                is_expected = "✅" if key == expected_key else "ℹ️"
                context_parts.append(f"  {is_expected} {key}: {value}")
        
        context_parts.append(f"- 시나리오 진행 관련: {'예 - 계속 진행' if state.scenario_agent_output.is_scenario_related else '아니오 - 다른 주제'}")
    
    # RAG Worker 응답
    if state.factual_response:
        worker_count += 1
        context_parts.append(f"\n### {worker_count}. 지식 기반 검색 (QA)")
        context_parts.append(f"- 답변: {state.factual_response}")
        context_parts.append("- 처리 방법: 간단히 답변 후 시나리오로 복귀")
    
    # Web Worker 응답 (있다면)
    if hasattr(state, 'web_search_response') and state.web_search_response:
        worker_count += 1
        context_parts.append(f"\n### {worker_count}. 웹 검색 결과")
        context_parts.append(state.web_search_response)
    
    # Worker가 하나도 없는 경우
    if worker_count == 0:
        context_parts.append("- Worker 호출 없음 (직접 응답 가능)")
    
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


def analyze_field_status(state: AgentState, scenario_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """시나리오 필드 수집 상태 분석"""
    if not scenario_data:
        return {
            'total_required': 0,
            'collected': 0,
            'remaining': 0,
            'current_stage_fields': []
        }
    
    required_fields = scenario_data.get("required_info_fields", [])
    collected_info = state.collected_product_info
    
    # 전체 필수 필드 상태
    total_required = sum(1 for f in required_fields if f.get("required", False))
    collected = sum(1 for f in required_fields if f.get("required", False) and collected_info.get(f["key"]) is not None)
    
    # 현재 단계와 관련된 필드들
    current_stage_fields = []
    stage_info = get_current_stage_info(state)
    
    if stage_info:
        # 현재 단계에서 수집하는 필드
        expected_key = stage_info.get("expected_info_key")
        if expected_key:
            for field in required_fields:
                if field["key"] == expected_key:
                    current_stage_fields.append({
                        'key': field["key"],
                        'display_name': field.get("display_name", field["key"]),
                        'collected': collected_info.get(field["key"]) is not None,
                        'value': collected_info.get(field["key"])
                    })
        
        # collect_multiple_info인 경우 관련된 모든 필드
        if stage_info.get("collect_multiple_info"):
            # visible_groups에 속한 필드들 찾기
            visible_groups = stage_info.get("visible_groups", [])
            for field in required_fields:
                field_group = field.get("group")  # 필드에 group 속성이 있다고 가정
                if field_group in visible_groups or not visible_groups:
                    # 부모 필드 조건 확인
                    parent_field = field.get("parent_field")
                    if parent_field:
                        parent_value = collected_info.get(parent_field)
                        show_when = field.get("show_when", "")
                        # 간단한 조건 평가 (예: "use_internet_banking == true")
                        if "==" in show_when:
                            parent_key, expected_val = show_when.split("==")
                            parent_key = parent_key.strip()
                            expected_val = expected_val.strip().strip("'\"")
                            if str(parent_value) != expected_val:
                                continue
                    
                    current_stage_fields.append({
                        'key': field["key"],
                        'display_name': field.get("display_name", field["key"]),
                        'collected': collected_info.get(field["key"]) is not None,
                        'value': collected_info.get(field["key"])
                    })
    
    return {
        'total_required': total_required,
        'collected': collected,
        'remaining': total_required - collected,
        'current_stage_fields': current_stage_fields
    }


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