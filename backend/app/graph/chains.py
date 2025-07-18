# backend/app/graph/chains.py

import json
from typing import Dict, Any, Sequence, cast, AsyncGenerator, Optional

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, AIMessageChunk
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_openai import ChatOpenAI

from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME
from .models import scenario_output_parser
from .state import ScenarioAgentOutput
from .utils import ALL_PROMPTS, format_messages_for_prompt, load_knowledge_base_content_async

# --- LLM Initialization ---
# This part remains the same
if not OPENAI_API_KEY:
    print("CRITICAL: OPENAI_API_KEY is not set. Check your .env file.")

json_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.1,
    model_kwargs={"response_format": {"type": "json_object"}}
) if OPENAI_API_KEY else None

generative_llm = ChatOpenAI(
    model=LLM_MODEL_NAME, openai_api_key=OPENAI_API_KEY, temperature=0.3, streaming=True
) if OPENAI_API_KEY else None


# --- Agent Logic / Chains (Our Tools) ---

async def invoke_scenario_agent_logic(
    user_input: str, current_stage_prompt: str, expected_info_key: Optional[str],
    messages_history: Sequence[BaseMessage], scenario_name: str
) -> ScenarioAgentOutput:
    """This function now acts as our 'Scenario NLU Tool'."""
    # This function's internal logic is good, no changes needed.
    # It correctly encapsulates the logic for extracting intent and entities.
    if not json_llm:
        return cast(ScenarioAgentOutput, {"intent": "error_llm_not_initialized", "entities": {}, "is_scenario_related": False})
    
    print(f"--- Calling Scenario Agent (Scenario: '{scenario_name}', Input: '{user_input[:50]}...') ---")
    prompt_template = ALL_PROMPTS.get('scenario_agent', {}).get('nlu_extraction', '')
    if not prompt_template:
        return cast(ScenarioAgentOutput, {"intent": "error_prompt_not_found", "entities": {}, "is_scenario_related": False})

    formatted_history = format_messages_for_prompt(messages_history)
    try:
        format_instructions = scenario_output_parser.get_format_instructions()
        prompt = prompt_template.format(
            scenario_name=scenario_name, current_stage_prompt=current_stage_prompt,
            expected_info_key=expected_info_key or "not specified",
            formatted_messages_history=formatted_history, user_input=user_input,
            format_instructions=format_instructions
        )
        response = await json_llm.ainvoke([HumanMessage(content=prompt)])
        raw_content = response.content.strip()
        if raw_content.startswith("```json"):
            raw_content = raw_content.replace("```json", "").replace("```", "").strip()
        
        parsed_output = scenario_output_parser.parse(raw_content).model_dump()
        print(f"Scenario Agent Result: {parsed_output}")
        return cast(ScenarioAgentOutput, parsed_output)
    except Exception as e:
        print(f"Scenario Agent processing error: {e}. LLM response: {getattr(e, 'llm_output', 'N/A')}")
        return cast(ScenarioAgentOutput, {"intent": "error_parsing_output", "entities": {}, "is_scenario_related": False})


# --- NEW: Synthesizer Chain ---
# This chain is responsible for creating the final, polished response.
synthesizer_prompt_template_str = ALL_PROMPTS.get('main_agent', {}).get('synthesizer_prompt', '')
if synthesizer_prompt_template_str and generative_llm:
    synthesizer_prompt_template = ChatPromptTemplate.from_template(synthesizer_prompt_template_str)
    synthesizer_chain = (
        {
            "chat_history": lambda x: format_messages_for_prompt(x["chat_history"]),
            "analysis_context": lambda x: x["analysis_context"],
        }
        | synthesizer_prompt_template
        | generative_llm
    )
else:
    synthesizer_chain = None