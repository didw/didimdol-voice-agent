# backend/app/graph/logger.py
"""
중앙 집중식 로깅 모듈
- LangGraph 노드 실행 추적
- PII 마스킹 지원
- 비동기 래퍼 제공
"""
import asyncio
import functools
import time
from typing import Any, Optional, Callable
from functools import wraps

# TODO: deepbrain_llm_log가 설치되면 아래 주석 해제
# from deepbrain_llm_log import LogManager
# log = LogManager.get_logger(__name__)

# 임시 로거 (개발 중)
class DevelopmentLogger:
    def info(self, msg: str, *args):
        # 필수 로그만 출력 (노드 이동, 주요 이벤트)
        if "🔄" in msg or "⏱️" in msg or "❌" in msg:
            if args:
                print(msg % args)
            else:
                print(msg)
    
    def error(self, msg: str, *args):
        if args:
            print(f"ERROR: {msg % args}")
        else:
            print(f"ERROR: {msg}")
    
    def warning(self, msg: str, *args):
        # 경고는 필수가 아니므로 무시
        pass

log = DevelopmentLogger()


def node_log(node_name: str, input_info: str = "", output_info: str = "") -> None:
    """
    노드 실행 추적을 위한 표준화된 로깅
    
    Args:
        node_name: 실행 중인 노드의 이름
        input_info: 입력 정보 요약 (선택적)
        output_info: 출력 정보 요약 (선택적)
    """
    # 필수 노드만 로깅
    essential_nodes = ['Session', 'Scenario_NLU', 'Scenario_Flow', 'Entity_Extract', 'Stage_Change']
    
    if node_name in essential_nodes:
        if input_info and output_info:
            log.info("🔄 [%s] %s → %s", node_name, input_info, output_info)
        elif input_info:
            log.info("🔄 [%s] %s", node_name, input_info)
        elif output_info:
            log.info("🔄 [%s] → %s", node_name, output_info)
        else:
            log.info("🔄 [%s]", node_name)


def log_execution_time(func: Callable) -> Callable:
    """노드 실행 시간을 측정하는 데코레이터"""
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        node_name = func.__name__.replace("_node", "").replace("_", " ").title()
        
        try:
            result = await func(*args, **kwargs)
            execution_time = time.time() - start_time
            log.info("⏱️ [%s] completed in %.2fs", node_name, execution_time)
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            log.error("❌ [%s] failed after %.2fs: %s", node_name, execution_time, str(e))
            raise
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        node_name = func.__name__.replace("_node", "").replace("_", " ").title()
        
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            log.info("⏱️ [%s] completed in %.2fs", node_name, execution_time)
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            log.error("❌ [%s] failed after %.2fs: %s", node_name, execution_time, str(e))
            raise
    
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def mask_pii(text: str) -> str:
    """
    PII(개인식별정보) 마스킹 - 간단한 버전
    실제 구현 시 deepbrain_llm_log의 마스킹 기능 사용
    """
    # 주민등록번호 패턴 마스킹
    import re
    text = re.sub(r'\d{6}-?\d{7}', '******-*******', text)
    # 전화번호 패턴 마스킹
    text = re.sub(r'01[0-9]-?\d{3,4}-?\d{4}', '010-****-****', text)
    # 이메일 일부 마스킹
    text = re.sub(r'([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', 
                  lambda m: f"{m.group(1)[:3]}***@{m.group(2)}", text)
    return text


def safe_log_state(state: dict, fields_to_log: Optional[list] = None) -> dict:
    """
    상태 객체의 안전한 로깅을 위한 필터링
    
    Args:
        state: 로깅할 상태 객체
        fields_to_log: 로깅할 필드 목록 (None이면 기본 필드만)
    
    Returns:
        안전하게 로깅 가능한 상태 딕셔너리
    """
    if fields_to_log is None:
        # 기본적으로 로깅할 안전한 필드들
        fields_to_log = [
            "session_id",
            "current_product_type", 
            "current_scenario_stage_id",
            "action_plan",
            "is_final_turn_response",
            "error_message"
        ]
    
    safe_state = {}
    for field in fields_to_log:
        if field in state:
            value = state[field]
            if isinstance(value, str):
                value = mask_pii(value)
            safe_state[field] = value
    
    return safe_state


# 기존 코드와의 호환성을 위한 별칭
log_node_execution = node_log