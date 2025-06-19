# backend/app/services/rag_service.py
from typing import Optional, List

from ..rag.rag_pipeline import VectorStoreManager, RAGPipeline
from ..graph.chains import generative_llm

class RAGService:
    """
    RAG 파이프라인의 생명주기를 관리하고, 어플리케이션 전체에서
    단일 인스턴스로 접근할 수 있도록 하는 싱글톤 서비스 클래스입니다.
    """
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(RAGService, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        # 초기화가 여러 번 실행되는 것을 방지
        if hasattr(self, '_initialized') and self._initialized:
            return
        self.vector_store_manager: Optional[VectorStoreManager] = None
        self.rag_pipeline: Optional[RAGPipeline] = None
        self._initialized = False
        print("RAGService instance created. Call initialize() to build the pipeline.")

    async def initialize(self, force_recreate: bool = False):
        """
        VectorStore와 RAG 파이프라인을 초기화합니다.
        이 메서드는 어플리케이션 시작 시 한 번만 호출되어야 합니다.
        """
        if self._initialized and not force_recreate:
            print("RAGService is already initialized.")
            return

        print("\n--- Initializing RAG Service ---")
        try:
            self.vector_store_manager = VectorStoreManager()
            self.vector_store_manager.initialize_vector_store(force_recreate=force_recreate)
            
            retriever = self.vector_store_manager.get_retriever(search_type="hybrid", k=5)
            
            if not generative_llm:
                raise ValueError("Generative LLM is not available.")
                
            self.rag_pipeline = RAGPipeline(retriever=retriever, llm=generative_llm)
            
            self._initialized = True
            print("--- RAG Service Initialized Successfully ---\n")
        except Exception as e:
            print(f"!!! RAG Service Initialization Failed: {e} !!!")
            # 실패 시, 파이프라인을 None으로 설정하여 사용 불가 상태로 만듭니다.
            self.rag_pipeline = None
            self._initialized = False
            # 에러를 다시 발생시켜 서버 시작 로직에서 인지할 수 있도록 합니다.
            raise

    def is_ready(self) -> bool:
        """RAG 파이프라인이 성공적으로 초기화되었는지 확인합니다."""
        return self._initialized and self.rag_pipeline is not None

    async def answer_question(self, questions: List[str], original_question: str) -> str:
        """
        주어진 질문 목록에 대해 RAG 파이프라인을 사용하여 답변을 생성합니다.
        """
        if not self.is_ready() or not self.rag_pipeline:
            print("Warning: RAG pipeline is not ready. Returning a default message.")
            return "죄송합니다, 현재 정보 검색 시스템에 문제가 있어 답변을 드릴 수 없습니다."
        
        try:
            rag_output = await self.rag_pipeline.ainvoke(questions, original_question)
            return rag_output.final_answer
        except Exception as e:
            print(f"Error during RAG question answering: {e}")
            return "답변을 생성하는 중 오류가 발생했습니다."

# 어플리케이션 전체에서 공유될 싱글톤 인스턴스
rag_service = RAGService() 