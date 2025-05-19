from openai import AsyncOpenAI # 비동기 클라이언트
from ..core.config import OPENAI_API_KEY, LLM_MODEL_NAME

if not OPENAI_API_KEY:
    print("OpenAI 서비스 경고: OPENAI_API_KEY가 설정되지 않았습니다.")

# AsyncOpenAI 클라이언트 초기화는 요청 시마다 할 수도 있고, 전역으로 한 번 할 수도 있습니다.
# 여기서는 요청 시마다 생성하는 예시를 보여주지만, 전역 인스턴스 사용도 고려할 수 있습니다.
# client = AsyncOpenAI(api_key=OPENAI_API_KEY)

async def get_llm_response(messages: list, model: str = LLM_MODEL_NAME) -> str:
    """
    OpenAI LLM으로부터 응답을 받습니다. (비동기)
    messages: [{"role": "user", "content": "Hello!"}, {"role": "assistant", "content": "Hi there!"}] 형식
    """
    if not OPENAI_API_KEY:
        raise EnvironmentError("OPENAI_API_KEY is not set.")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY) # 각 요청마다 클라이언트 생성

    print(f"OpenAI LLM ({model}) 요청 중...")
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            # stream=True # 스트리밍 응답을 원할 경우
        )
        # if stream:
        #   async for chunk in response:
        #     # process chunk
        # else:
        #   return response.choices[0].message.content
        content = response.choices[0].message.content
        print(f"LLM 응답: {content[:50]}...")
        return content
    except Exception as e:
        print(f"OpenAI LLM Error: {e}")
        return "죄송합니다, 현재 서비스에 문제가 발생했습니다. 잠시 후 다시 시도해주세요."

# 스트리밍 응답을 위한 함수 (LangGraph에서 사용하기 좋음)
async def stream_llm_response(messages: list, model: str = LLM_MODEL_NAME):
    if not OPENAI_API_KEY:
        raise EnvironmentError("OPENAI_API_KEY is not set.")

    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    print(f"OpenAI LLM ({model}) 스트리밍 요청 중...")
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content
    except Exception as e:
        print(f"OpenAI LLM Streaming Error: {e}")
        yield "죄송합니다, 스트리밍 중 오류가 발생했습니다."