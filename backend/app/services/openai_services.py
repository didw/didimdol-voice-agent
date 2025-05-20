# backend/app/services/openai_services.py
from openai import AsyncOpenAI, APIError # APIError 추가
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME

if not OPENAI_API_KEY:
    print("OpenAI 서비스 경고: OPENAI_API_KEY가 설정되지 않았습니다. OpenAI 서비스 기능이 비활성화될 수 있습니다.")

# 전역 클라이언트 인스턴스 (애플리케이션 생애주기 동안 재사용)
# 단, OPENAI_API_KEY가 없을 경우 None으로 유지하고, 사용 시점에서 확인
aclient: Optional[AsyncOpenAI] = None
if OPENAI_API_KEY:
    aclient = AsyncOpenAI(api_key=OPENAI_API_KEY)
else:
    print("OpenAI AsyncClient가 초기화되지 않았습니다. API 키를 확인하세요.")


async def get_llm_response_non_streaming(messages: list, model: str = LLM_MODEL_NAME) -> str:
    """OpenAI LLM으로부터 일반 응답을 받습니다. (비동기, 단건 응답)"""
    if not aclient:
        return "죄송합니다, LLM 서비스 초기화에 실패했습니다. (API 키 오류)"
    
    print(f"OpenAI LLM ({model}) 요청 중 (Non-streaming)... 첫 메시지: {messages[0] if messages else '없음'}")
    try:
        response = await aclient.chat.completions.create(
            model=model,
            messages=messages,
        )
        content = response.choices[0].message.content
        print(f"LLM 응답 (Non-streaming): {content[:70]}...")
        return content if content else ""
    except APIError as e: # 구체적인 OpenAI API 에러 처리
        print(f"OpenAI API Error (Non-streaming): {e.status_code} - {e.message}")
        return f"죄송합니다, LLM 서비스 요청 중 오류가 발생했습니다. (API 에러: {e.status_code})"
    except Exception as e:
        print(f"OpenAI LLM Error (Non-streaming): {type(e).__name__} - {e}")
        return "죄송합니다, LLM 서비스에 예상치 못한 문제가 발생했습니다."


async def stream_llm_response_langchain(messages: list, model: str = LLM_MODEL_NAME):
    """
    OpenAI LLM으로부터 스트리밍 응답을 받습니다. (Langchain/LangGraph용)
    Langchain의 ChatOpenAI에서 streaming=True로 설정 시 내부적으로 유사한 로직 사용.
    이 함수는 직접 OpenAI SDK를 사용하여 LangGraph 외부에서 스트리밍할 때 유용.
    LangGraph 내에서는 ChatOpenAI(streaming=True) 사용 권장.
    """
    if not aclient:
        yield "죄송합니다, LLM 서비스 초기화에 실패했습니다. (API 키 오류)"
        return

    print(f"OpenAI LLM ({model}) 스트리밍 요청 중... 첫 메시지: {messages[0] if messages else '없음'}")
    try:
        stream = await aclient.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
    except APIError as e:
        print(f"OpenAI API Error (Streaming): {e.status_code} - {e.message}")
        yield f"죄송합니다, LLM 스트리밍 중 API 오류가 발생했습니다. (코드: {e.status_code})"
    except Exception as e:
        print(f"OpenAI LLM Streaming Error: {type(e).__name__} - {e}")
        yield "죄송합니다, LLM 스트리밍 중 예상치 못한 오류가 발생했습니다."