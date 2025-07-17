# backend/app/graph/nodes/orchestrator/main_router.py
"""
메인 오케스트레이터 노드 - 사용자 입력을 분석하여 적절한 워커로 라우팅
"""
import json
import yaml
import traceback
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage

from ...state import AgentState
from ...state_utils import ensure_pydantic_state, ensure_dict_state
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
    메인 오케스트레이터 노드 - Pydantic 버전
    - 사용자 입력 분석
    - 적절한 워커 결정
    - 액션 플랜 생성
    """
    # Convert to Pydantic for internal processing
    pydantic_state = ensure_pydantic_state(state)
    
    user_input = pydantic_state.stt_result or ""
    current_product_type = pydantic_state.current_product_type
    mode = "business_guidance" if not current_product_type else "task_management"
    log_node_execution("Orchestrator", f"mode={mode}, input='{user_input[:20]}...'")
    
    if not json_llm:
        return ensure_dict_state(pydantic_state.merge_update({
            "error_message": "Orchestrator service unavailable (LLM not initialized).",
            "is_final_turn_response": True
        }))

    # LLM 기반 대화 처리 및 Worker 결정
    prompt_key = 'business_guidance_prompt' if not current_product_type else 'task_management_prompt'
    log_node_execution("Orchestrator", f"prompt={prompt_key}")

    prompt_template = ALL_PROMPTS.get('main_agent', {}).get(prompt_key, '')
    if not prompt_template:
        return ensure_dict_state(pydantic_state.merge_update({
            "error_message": "Router prompt not found.",
            "main_agent_routing_decision": "unclear_input",
            "is_final_turn_response": True
        }))

    parser = initial_task_decision_parser if not current_product_type else main_router_decision_parser
    format_instructions = parser.get_format_instructions()
    
    try:
        prompt_kwargs = {"user_input": user_input, "format_instructions": format_instructions}
        
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
             active_scenario_data = get_active_scenario_data(pydantic_state.to_dict()) or {}
             current_stage_id = pydantic_state.current_scenario_stage_id or "N/A"
             current_stage_info = active_scenario_data.get("stages", {}).get(str(current_stage_id), {})
             valid_choices = current_stage_info.get("choices", []) 
             available_types = ", ".join([ALL_SCENARIOS_DATA[pt]["scenario_name"] for pt in pydantic_state.available_product_types if pt in ALL_SCENARIOS_DATA])
             
             # 업무 관련 JSON 정보 추가
             task_context = {
                 "collected_info": pydantic_state.collected_product_info,
                 "current_stage": current_stage_info,
                 "stage_id": current_stage_id,
                 "expected_info_key": current_stage_info.get("expected_info_key", ""),
                 "valid_choices": valid_choices
             }
             
             # 매뉴얼 정보 로드
             product_type = pydantic_state.current_product_type
             manual_content = await load_knowledge_base_content_async(product_type) if product_type else ""
             
             prompt_kwargs.update({
                "active_scenario_name": pydantic_state.active_scenario_name or "Not Selected",
                "formatted_messages_history": format_messages_for_prompt(list(pydantic_state.messages)[:-1]),
                "task_context_json": json.dumps(task_context, ensure_ascii=False, indent=2),
                "manual_content": manual_content[:2000] if manual_content else "매뉴얼 정보 없음",
                "available_product_types_display": available_types
             })
        else:
            # 초기 프롬프트에 필요한 available_product_types_list를 추가합니다.
            available_types_list = pydantic_state.available_product_types
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

        state_updates = {}
        if hasattr(decision, 'direct_response') and decision.direct_response:
            state_updates["main_agent_direct_response"] = decision.direct_response

        system_log = f"Main Agent Plan: actions={[f'{a.tool}({a.tool_input})' for a in action_plan_models]}"
        updated_messages = list(pydantic_state.messages) + [SystemMessage(content=system_log)]
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
        
        # Update with Pydantic and return dict
        updated_state = pydantic_state.merge_update(state_updates)
        return ensure_dict_state(updated_state)

    except Exception as e:
        log_node_execution("Orchestrator", f"ERROR: {e}")
        traceback.print_exc()
        err_msg = "Error processing request. Please try again."
        return ensure_dict_state(pydantic_state.merge_update({
            "error_message": err_msg,
            "main_agent_routing_decision": "unclear_input",
            "is_final_turn_response": True
        }))