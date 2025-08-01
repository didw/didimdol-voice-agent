"""
스테이지 응답 생성 관련 함수들
"""
from typing import Dict, Any, List
from .scenario_utils import get_default_choice_display, format_field_value
from .response_generation import generate_final_confirmation_prompt
from .scenario_helpers import replace_template_variables


def generate_stage_response(stage_info: Dict[str, Any], collected_info: Dict[str, Any], scenario_data: Dict = None) -> Dict[str, Any]:
    """단계별 응답 유형에 맞는 데이터 생성"""
    response_type = stage_info.get("response_type", "narrative")
    stage_id = stage_info.get("stage_id", "unknown")
    
    
    # final_confirmation 단계의 동적 프롬프트 생성
    if stage_id == "final_confirmation":
        prompt = generate_final_confirmation_prompt(collected_info)
        print(f"🎯 [FINAL_CONFIRMATION] Generated dynamic prompt: {prompt}")
    # dynamic_prompt 처리 우선 (V3 시나리오)
    elif stage_info.get("dynamic_prompt"):
        default_choice = get_default_choice_display(stage_info)
        prompt = stage_info["dynamic_prompt"].replace("{default_choice}", default_choice)
        print(f"🎯 [DYNAMIC_PROMPT] Used dynamic_prompt with default_choice: '{default_choice}'")
    else:
        prompt = stage_info.get("prompt", "")
    
    
    
    # display_fields가 있는 경우 처리 (bullet 타입)
    if stage_info.get("display_fields"):
        # V3 시나리오: display_fields가 dict인 경우 (실제 값이 포함됨)
        if isinstance(stage_info["display_fields"], dict):
            # V3 시나리오의 display_fields는 이미 포맷된 데이터이므로 바로 사용
            display_values = stage_info["display_fields"]
            field_display = []
            for field_name, value in display_values.items():
                field_display.append(f"- {field_name}: {value}")
            
            # 프롬프트에 개인정보 추가
            if field_display:
                prompt = prompt + "\n\n" + "\n".join(field_display)
                print(f"🎯 [V3_DISPLAY_FIELDS] Added {len(field_display)} fields to prompt")
        else:
            # 기존 방식: display_fields가 list인 경우
            prompt = format_prompt_with_fields(prompt, collected_info, stage_info["display_fields"], scenario_data)
    
    # 템플릿 변수 치환
    prompt = replace_template_variables(prompt, collected_info)
    
    response_data = {
        "stage_id": stage_info.get("stage_id"),
        "stageId": stage_info.get("stage_id"),  # camelCase for frontend compatibility
        "response_type": response_type,
        "responseType": response_type,  # camelCase for frontend compatibility  
        "prompt": prompt,
        "skippable": stage_info.get("skippable", False)
    }
    
    # additional_questions가 있는 경우 추가
    if stage_info.get("additional_questions"):
        questions = stage_info.get("additional_questions", [])
        response_data["additional_questions"] = questions
        response_data["additionalQuestions"] = questions  # camelCase for frontend compatibility
    
    # 선택지가 있는 경우
    if response_type in ["bullet", "boolean"]:
        response_data["choices"] = stage_info.get("choices", [])
        # choice_groups가 있는 경우 추가 (frontend 형식으로 변환)
        if stage_info.get("choice_groups"):
            print(f"🎯 [CHOICE_GROUPS] Found choice_groups in stage_info: {stage_info.get('choice_groups')}")
            choice_groups = []
            for group in stage_info.get("choice_groups", []):
                # choices도 frontend 형식으로 변환
                transformed_choices = []
                for choice in group.get("choices", []):
                    transformed_choice = {
                        "value": choice.get("value", ""),
                        "label": choice.get("display", choice.get("label", "")),
                        "display": choice.get("display", choice.get("label", "")),
                        "default": choice.get("default", False)
                    }
                    # metadata가 있으면 포함
                    if choice.get("metadata"):
                        transformed_choice["metadata"] = choice.get("metadata")
                    transformed_choices.append(transformed_choice)
                    print(f"🎯 [CHOICE_GROUPS] Transformed choice: {transformed_choice}")
                
                transformed_group = {
                    "title": group.get("group_name", ""),
                    "items": transformed_choices
                }
                choice_groups.append(transformed_group)
                print(f"🎯 [CHOICE_GROUPS] Transformed group: {transformed_group}")
            
            response_data["choice_groups"] = choice_groups
            response_data["choiceGroups"] = choice_groups  # camelCase for frontend compatibility
            
            # choice_groups에서 default choice 찾아서 top-level에 설정
            default_choice_value = None
            for group in choice_groups:
                for item in group.get("items", []):
                    if item.get("default"):
                        default_choice_value = item.get("value")
                        break
                if default_choice_value:
                    break
            
            if default_choice_value:
                response_data["default_choice"] = default_choice_value
                response_data["defaultChoice"] = default_choice_value  # camelCase for frontend compatibility
                print(f"🎯 [CHOICE_GROUPS] Set default choice from choice_groups: {default_choice_value}")
            
            print(f"🎯 [CHOICE_GROUPS] Final choice_groups in response_data: {response_data['choice_groups']}")
            print(f"🎯 [CHOICE_GROUPS] Added choiceGroups (camelCase) for frontend compatibility")
            print(f"🎯 [CHOICE_GROUPS] Transformed {len(choice_groups)} groups with {sum(len(g['items']) for g in choice_groups)} total choices for frontend")
        # default_choice가 있는 경우 추가
        if stage_info.get("default_choice"):
            response_data["default_choice"] = stage_info.get("default_choice")
            response_data["defaultChoice"] = stage_info.get("default_choice")  # camelCase for frontend compatibility
        
    
    # 수정 가능한 필드 정보
    if stage_info.get("modifiable_fields"):
        response_data["modifiable_fields"] = stage_info["modifiable_fields"]
        response_data["modifiableFields"] = stage_info["modifiable_fields"]  # camelCase for frontend compatibility
    
    # display_fields 정보 추가 (V3 시나리오)
    if stage_info.get("display_fields"):
        if isinstance(stage_info["display_fields"], dict):
            # V3: display_fields가 실제 값을 포함하는 경우
            display_values = stage_info["display_fields"]
            merged_values = {**display_values, **collected_info}  # collected_info가 우선
            response_data["display_fields"] = merged_values
        else:
            # 기존: display_fields가 필드명 리스트인 경우
            response_data["display_fields"] = stage_info["display_fields"]
    
    return response_data


def format_prompt_with_fields(prompt: str, collected_info: Dict[str, Any], display_fields: List[str], scenario_data: Dict = None) -> str:
    """프롬프트에 수집된 정보 동적 삽입 (기본값 포함)"""
    field_display = []
    
    field_names = {
        "customer_name": "이름",
        "english_name": "영문이름", 
        "resident_number": "주민등록번호",
        "phone_number": "휴대폰번호", 
        "customer_phone": "휴대폰번호",
        "email": "이메일",
        "address": "집주소",
        "work_address": "직장주소"
    }
    
    # 기본값 매핑
    default_values = {
        "customer_name": "홍길동",
        "phone_number": "010-1234-5678", 
        "address": "서울특별시 종로구 숭인동 123"
    }
    
    # 시나리오 데이터에서 기본값 가져오기
    if scenario_data:
        for field in scenario_data.get("required_info_fields", []):
            if field.get("key") in display_fields and field.get("default"):
                default_values[field["key"]] = field["default"]
    
    # 프롬프트에 이미 필드 정보가 포함되어 있는지 확인
    # "- 성함:" 같은 패턴이 이미 있으면 중복 추가하지 않음
    prompt_has_fields = False
    for field_key in display_fields:
        field_name = field_names.get(field_key, field_key)
        if f"- {field_name}:" in prompt:
            prompt_has_fields = True
            break
    
    # 프롬프트에 필드 정보가 없을 때만 추가
    if not prompt_has_fields:
        for field_key in display_fields:
            # 수집된 정보가 있으면 사용, 없으면 기본값 사용
            value = collected_info.get(field_key)
            if not value and field_key in default_values:
                value = default_values[field_key]
            if not value:
                value = "미입력"
                
            field_name = field_names.get(field_key, field_key)
            field_display.append(f"- {field_name}: {value}")
        
        if field_display:
            prompt += "\n" + "\n".join(field_display)
    
    return prompt