# backend/app/rag/models.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class RetrievedDocument(BaseModel):
    """
    검색 쿼리를 통해 검색된 문서를 나타내며, 확장성을 고려하여 설계되었습니다.
    """
    page_content: str = Field(description="문서 청크의 실제 텍스트 내용입니다.")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="문서와 관련된 메타데이터입니다. (예: 출처, 페이지 번호)")
    score: Optional[float] = Field(None, description="검색 결과에서의 문서 관련성 점수입니다.")

class ProcessedDocument(BaseModel):
    """
    검색된 단일 문서와, 그 문서를 기반으로 생성된 요약 답변 및 관련 정보를 관리합니다.
    """
    query: str = Field(description="이 문서를 처리하는 데 사용된 원본 또는 재구성된 질문입니다.")
    source_document: RetrievedDocument = Field(description="검색을 통해 찾은 원본 문서입니다.")
    generated_answer: str = Field(description="원본 문서를 기반으로 질문에 대해 생성된 요약 답변입니다.")

class RAGOutput(BaseModel):
    """
    전체 RAG 파이프라인의 최종 출력을 나타냅니다.
    """
    final_answer: str = Field(description="최종적으로 종합된 답변입니다.")
    processed_documents: List[ProcessedDocument] = Field(description="검색 및 처리된 모든 문서와 그 결과의 목록입니다.") 