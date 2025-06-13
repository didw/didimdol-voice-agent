# tools.py

from typing import Optional, Sequence, cast, AsyncGenerator, Dict, Any

# config.py 파일이 프로젝트 루트에 있고, OPENAI_API_KEY와 LLM_MODEL_NAME을 정의한다고 가정합니다.
# from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
# 아래는 예시입니다. 실제 환경에 맞게 수정하세요.
from .config import OPENAI_API_KEY, LLM_MODEL_NAME

from langchain_core.messages import BaseMessage, HumanMessage, AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

# 다른 모듈에서 필요한 요소들을 가져옵니다.
from .prompts import ALL_PROMPTS, scenario_output_parser
from .utils import format_messages_for_prompt, ScenarioAgentOutput

# --- LLM 초기화 ---
if not OPENAI_API_KEY:
    print("CRITICAL: OPENAI_API_KEY가 설정되지 않았습니다. .env 또는 config 파일을 확인하세요.")

# JSON 출력을 강제하는 LLM (라우팅, 정보 추출 등 구조화된 데이터 필요시 사용)
json_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.1,
    model_kwargs={"response_format": {"type": "json_object"}}
) if OPENAI_API_KEY else None

# 일반 텍스트 생성을 위한 LLM (스트리밍 및 일반 답변 생성용)
generative_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.3, streaming=True
) if OPENAI_API_KEY else None


# --- 답변 합성 체인 ---
synthesizer_prompt_template_str = ALL_PROMPTS.get('main_agent', {}).get('synthesizer_prompt', 'An error occurred: synthesizer_prompt not found.')
synthesizer_prompt_template = ChatPromptTemplate.from_template(synthesizer_prompt_template_str)

synthesizer_chain = (
    {
        "chat_history": lambda x: format_messages_for_prompt(x["chat_history"]),
        "user_question": lambda x: x["user_question"],
        "contextual_response": lambda x: x["contextual_response"],
        "factual_response": lambda x: x["factual_response"],
    }
    | synthesizer_prompt_template
    | generative_llm
) if generative_llm and 'not found' not in synthesizer_prompt_template_str else None


# --- 에이전트 호출 로직 (도구) ---

async def invoke_scenario_agent_logic(
    user_input: str, current_stage_prompt: str, expected_info_key: Optional[str],
    messages_history: Sequence[BaseMessage], scenario_name: str
) -> ScenarioAgentOutput:
    """
    사용자 입력으로부터 의도와 개체를 추출하는 Scenario Agent (NLU)를 호출합니다.
    """
    if not json_llm:
        return cast(ScenarioAgentOutput, {"intent": "error_llm_not_initialized", "entities": {}, "is_scenario_related": False})
    
    print(f"--- Scenario Agent 호출 (시나리오: '{scenario_name}', 입력: '{user_input[:50]}...') ---")
    prompt_template = ALL_PROMPTS.get('scenario_agent', {}).get('nlu_extraction', '')
    if not prompt_template:
        return cast(ScenarioAgentOutput, {"intent": "error_prompt_not_found", "entities": {}, "is_scenario_related": False})

    formatted_history = format_messages_for_prompt(messages_history)
    try:
        format_instructions = scenario_output_parser.get_format_instructions()
        formatted_prompt = prompt_template.format(
            scenario_name=scenario_name, current_stage_prompt=current_stage_prompt,
            expected_info_key=expected_info_key or "특정 정보 없음",
            formatted_messages_history=formatted_history, user_input=user_input,
            format_instructions=format_instructions
        )
        response = await json_llm.ainvoke([HumanMessage(content=formatted_prompt)])
        raw_response_content = response.content.strip()
        print(f"LLM Raw Response: {raw_response_content}")
        
        if raw_response_content.startswith("```json"):
            raw_response_content = raw_response_content.replace("```json", "").replace("```", "").strip()
        
        parsed_output = scenario_output_parser.parse(raw_response_content)
        parsed_output_dict = parsed_output.model_dump()
        print(f"Scenario Agent 결과: {parsed_output_dict}")
        return cast(ScenarioAgentOutput, parsed_output_dict)
    except Exception as e:
        response_content = getattr(e, 'llm_output', getattr(locals().get('response'), 'content', 'N/A'))
        print(f"Scenario Agent 처리 오류: {e}. LLM 응답: {response_content}")
        return cast(ScenarioAgentOutput, {"intent": "error_parsing_scenario_output", "entities": {}, "is_scenario_related": False})


async def invoke_qa_agent_streaming_logic(user_question: str, scenario_name: str, knowledge_base_text: Optional[str]) -> AsyncGenerator[str, None]:
    """
    지식 베이스를 바탕으로 사용자 질문에 답변하는 QA Agent(RAG)를 호출하고, 답변을 스트리밍합니다.
    """
    if not generative_llm:
        yield "죄송합니다, 답변 생성 서비스가 현재 사용할 수 없습니다. (LLM 초기화 오류)"
        return
    
    print(f"--- QA Agent 스트리밍 호출 (컨텍스트: '{scenario_name}', 질문: '{user_question[:50]}...') ---")
    
    context_for_llm: str
    if knowledge_base_text:
        context_for_llm = knowledge_base_text
    else:
        # 지식베이스가 없는 일반 질의
        context_for_llm = "특정 상품 문서가 제공되지 않았습니다. 일반적인 금융 상식 또는 사용자의 질문 자체에만 기반하여 답변해주세요."
        print("QA Agent (일반): 특정 문서 없이 답변 생성 시도")

    prompt_template = ALL_PROMPTS.get('qa_agent', {}).get('rag_answer_generation', '')
    if not prompt_template:
        yield "죄송합니다, 답변 생성에 필요한 설정(프롬프트)을 찾을 수 없습니다."
        return

    formatted_prompt = prompt_template.format(
        scenario_name=scenario_name, 
        context_for_llm=context_for_llm, 
        user_question=user_question
    )
    
    try:
        async for chunk in generative_llm.astream([HumanMessage(content=formatted_prompt)]):
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                yield str(chunk.content)
    except Exception as e:
        print(f"QA Agent 스트리밍 처리 오류: {e}")
        yield f"질문 답변 중 시스템 오류가 발생했습니다: {str(e)}"