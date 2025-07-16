"""
유틸리티 함수들
"""

import re
from typing import List


def split_into_sentences(text: str) -> List[str]:
    """
    텍스트를 문장으로 분리합니다.
    더 정교한 문장 분리를 위해서는 KSS (Korean Sentence Splitter) 또는 NLTK 사용을 고려하세요.
    """
    if not text:
        return []
    
    # 한국어 및 영어 문장 종료 표시자를 찾아 분리
    # 구두점 뒤의 공백으로 분리하되, 대문자나 따옴표 앞의 공백을 기준으로 함
    parts = re.split(r'(?<=[.?!다죠요])\s+|(?<=[.?!])\s+(?=[A-Z"\'(])', text)
    
    processed_sentences = []
    for part in parts:
        if part and part.strip():
            processed_sentences.append(part.strip())
            
    if not processed_sentences and text.strip():
        return [text.strip()]
        
    return [s for s in processed_sentences if s]