# backend/app/graph/nodes/orchestrator/main_router.py
"""
메인 오케스트레이터 노드 - 사용자 입력을 분석하여 적절한 워커로 라우팅
"""
import json
import yaml
import asyncio
import traceback
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage

from ...state import AgentState
from ...models import initial_task_decision_parser, main_router_decision_parser, ActionModel
from ...utils import (
    ALL_PROMPTS, 
    ALL_SCENARIOS_DATA, 
    get_active_scenario_data,
    load_knowledge_base_content_async,
    format_messages_for_prompt
)
from ...chains import json_llm
from ...logger import node_log as log_node_execution, log_execution_time


@log_execution_time
async def main_agent_router_node(state: AgentState) -> AgentState:
    """
    메인 오케스트레이터 노드
    - 사용자 입력 분석
    - 적절한 워커 결정
    - 액션 플랜 생성
    """
    user_input = state.stt_result or ""
    current_product_type = state.current_product_type
    mode = "business_guidance" if not current_product_type else "task_management"
    log_node_execution("Orchestrator", f"mode={mode}, input='{user_input[:20]}...'")
    
    # customer_info_check 단계에서만 수정 관련 플래그를 처리
    current_stage_id = state.current_scenario_stage_id or "greeting"
    if ((state.waiting_for_additional_modifications or state.pending_modifications) and 
        current_stage_id == "customer_info_check"):
        log_node_execution("Orchestrator", f"Routing to personal_info_correction (waiting_for_additional_modifications={state.waiting_for_additional_modifications}, pending_modifications={state.pending_modifications})")
        return state.merge_update({
            "action_plan": ["personal_info_correction"],
            "action_plan_struct": [{"action": "personal_info_correction", "reason": "Handle pending modifications or additional modifications"}],
            "router_call_count": 0,
            "is_final_turn_response": False
        })
    
    if not json_llm:
        return state.merge_update({
            "error_message": "Orchestrator service unavailable (LLM not initialized).",
            "is_final_turn_response": True
        })

    # Scenario stage protection - bypass LLM for specific stages
    scenario_stages_protect = ["statement_delivery", "card_selection", "additional_services", "card_usage_alert", "security_medium_registration"]
    if current_product_type and current_stage_id in scenario_stages_protect:
        log_node_execution("Orchestrator", f"Scenario stage {current_stage_id} detected - routing directly to scenario_agent")
        return state.merge_update({
            "action_plan": ["invoke_scenario_agent"],
            "action_plan_struct": [{
                "action": "invoke_scenario_agent",
                "reason": f"Processing scenario stage {current_stage_id}"
            }],
            "router_call_count": 0,
            "is_final_turn_response": False
        })
    
    # LLM 기반 대화 처리 및 Worker 결정
    prompt_key = 'business_guidance_prompt' if not current_product_type else 'task_management_prompt'
    log_node_execution("Orchestrator", f"prompt={prompt_key}")

    prompt_template = ALL_PROMPTS.get('main_agent', {}).get(prompt_key, '')
    if not prompt_template:
        return state.merge_update({
            "error_message": "Router prompt not found.",
            "main_agent_routing_decision": "unclear_input",
            "is_final_turn_response": True
        })

    parser = initial_task_decision_parser if not current_product_type else main_router_decision_parser
    format_instructions = parser.get_format_instructions()
    
    try:
        # 현재 stage 정보 추가
        current_stage = state.get("current_scenario_stage_id", "")
        prompt_kwargs = {
            "user_input": user_input, 
            "format_instructions": format_instructions,
            "current_stage": current_stage
        }
        
        # business_guidance_prompt에 서비스 설명 추가
        if not current_product_type:
            # service_descriptions.yaml 로드
            service_desc_path = Path(__file__).parent.parent.parent / "config" / "service_descriptions.yaml"
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
             active_scenario_data = get_active_scenario_data(state.to_dict()) or {}
             current_stage_id = state.current_scenario_stage_id or "N/A"
             current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
             valid_choices = current_stage_info.get("choices", []) 
             available_types = ", ".join([ALL_SCENARIOS_DATA[pt]["scenario_name"] for pt in state.available_product_types if pt in ALL_SCENARIOS_DATA])
             
             # 업무 관련 JSON 정보 추가
             task_context = {
                 "collected_info": state.collected_product_info,
                 "current_stage": current_stage_info,
                 "stage_id": current_stage_id,
                 "expected_info_key": current_stage_info.get("expected_info_key", ""),
                 "valid_choices": valid_choices
             }
             
             # 매뉴얼 정보 로드
             product_type = state.current_product_type
             manual_content = await load_knowledge_base_content_async(product_type) if product_type else ""
             
             prompt_kwargs.update({
                "active_scenario_name": state.active_scenario_name or "Not Selected",
                "formatted_messages_history": format_messages_for_prompt(list(state.messages)[:-1]),
                "task_context_json": json.dumps(task_context, ensure_ascii=False, indent=2),
                "manual_content": manual_content[:2000] if manual_content else "매뉴얼 정보 없음",
                "available_product_types_display": available_types
             })
        else:
            # 초기 프롬프트에 필요한 available_product_types_list를 추가합니다.
            available_types_list = state.available_product_types
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
        
        # Debug logging for stage-based routing issues
        if current_stage in ["statement_delivery", "card_selection", "additional_services", "card_usage_alert", "security_medium_registration"]:
            print(f"🔍 [DEBUG] Main Router - Current stage: '{current_stage}' is a scenario stage")
            print(f"🔍 [DEBUG] Main Router - User input: '{user_input}'")
            print(f"🔍 [DEBUG] Main Router - Should route to invoke_scenario_agent")
        
        # Add retry logic for API errors
        max_retries = 3
        retry_delay = 1.0
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = await json_llm.ainvoke([HumanMessage(content=prompt_filled)])
                raw_content = response.content.strip().replace("```json", "").replace("```", "").strip()
                decision = parser.parse(raw_content)
                
                # Debug logging for decision
                if current_stage in ["statement_delivery", "card_selection", "additional_services", "card_usage_alert", "security_medium_registration"]:
                    print(f"🔍 [DEBUG] Main Router - LLM Decision: {[action.tool for action in decision.actions]}")
                    if decision.actions and decision.actions[0].tool == "personal_info_correction":
                        print(f"❌ [DEBUG] Main Router - ERROR: LLM chose personal_info_correction for scenario stage!")
                
                break  # Success, exit retry loop
            except Exception as e:
                last_error = e
                # Check if it's a rate limit error
                if hasattr(e, '__class__') and e.__class__.__name__ == 'RateLimitError':
                    if attempt < max_retries - 1:
                        print(f"🔄 [Main Router] Rate limit hit, retrying in {retry_delay}s... (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        # After all retries, provide a specific error message
                        print(f"❌ [Main Router] Rate limit exceeded after {max_retries} attempts")
                        return state.merge_update({
                            "error_message": "죄송합니다. 현재 서비스 이용량이 많아 잠시 후 다시 시도해주세요.",
                            "main_agent_routing_decision": "rate_limit_error",
                            "is_final_turn_response": True,
                            "final_response_text_for_tts": "죄송합니다. 현재 서비스 이용량이 많아 잠시 후 다시 시도해주세요."
                        })
                # For non-rate-limit errors, raise immediately
                raise e
        else:
            # All retries failed
            if last_error:
                raise last_error

        # 새로운 ActionModel 구조를 사용하도록 상태 업데이트
        action_plan_models = decision.actions

        state_updates = {}
        if hasattr(decision, 'direct_response') and decision.direct_response:
            state_updates["main_agent_direct_response"] = decision.direct_response

        system_log = f"Main Agent Plan: actions={[f'{a.tool}({a.tool_input})' for a in action_plan_models]}"
        updated_messages = list(state.messages) + [SystemMessage(content=system_log)]
        state_updates["messages"] = updated_messages

        # 초기 상태 분기 처리: action_plan_models 자체를 수정하여 일관성 유지
        if not current_product_type:
            first_action = action_plan_models[0] if action_plan_models else None
            if first_action:
                if first_action.tool == "set_product_type":
                    state_updates["loan_selection_is_fresh"] = True
                elif first_action.tool == "invoke_qa_agent_general":
                    # action_plan_models의 tool 이름을 직접 변경
                    first_action.tool = "invoke_qa_agent"
                    state_updates["active_scenario_name"] = "General Financial Advice"
                elif first_action.tool == "clarify_product_type":
                    # action_plan_models의 tool 이름을 직접 변경
                    first_action.tool = "select_product_type"

        # 최종적으로 결정된 모델에서 action_plan과 action_plan_struct를 생성
        state_updates["action_plan"] = [model.tool for model in action_plan_models]
        state_updates["action_plan_struct"] = [model.model_dump() for model in action_plan_models]

        action_plan = state_updates.get('action_plan', [])
        direct_resp = state_updates.get('main_agent_direct_response', '')
        if direct_resp:
            log_node_execution("Orchestrator", output_info=f"direct_response='{direct_resp[:30]}...'")
        else:
            log_node_execution("Orchestrator", output_info=f"plan={action_plan}")
        
        # Update with Pydantic and return
        updated_state = state.merge_update(state_updates)
        return updated_state

    except Exception as e:
        log_node_execution("Orchestrator", f"ERROR: {e}")
        traceback.print_exc()
        
        # Provide more specific error messages based on error type
        if hasattr(e, '__class__'):
            error_type = e.__class__.__name__
            if error_type == 'RateLimitError':
                err_msg = "죄송합니다. 현재 서비스 이용량이 많아 잠시 후 다시 시도해주세요."
                final_response = "죄송합니다. 현재 서비스 이용량이 많아 잠시 후 다시 시도해주세요."
            elif error_type == 'APIConnectionError':
                err_msg = "네트워크 연결에 문제가 있습니다. 잠시 후 다시 시도해주세요."
                final_response = "네트워크 연결에 문제가 있습니다. 잠시 후 다시 시도해주세요."
            elif error_type == 'JSONDecodeError':
                err_msg = "응답 처리 중 오류가 발생했습니다."
                final_response = "죄송합니다. 다시 한 번 말씀해주시겠어요?"
            else:
                err_msg = f"처리 중 오류가 발생했습니다. ({error_type})"
                final_response = "죄송합니다. 다시 한 번 말씀해주시겠어요?"
        else:
            err_msg = "처리 중 오류가 발생했습니다."
            final_response = "죄송합니다. 다시 한 번 말씀해주시겠어요?"
        
        return state.merge_update({
            "error_message": err_msg,
            "main_agent_routing_decision": "error",
            "is_final_turn_response": True,
            "final_response_text_for_tts": final_response
        })