# backend/app/rag/rag_pipeline.py
import lancedb
from pathlib import Path
from typing import List, Dict, Any, Optional
import asyncio

from langchain_community.document_loaders import DirectoryLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import LanceDB
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document

from ..core.config import OPENAI_API_KEY
from ..graph.chains import generative_llm
from .models import RetrievedDocument, ProcessedDocument, RAGOutput

# --- Constants ---
LANCEDB_PATH = Path(__file__).parent / ".lancedb"
DATA_PATH = Path(__file__).parent.parent / "data"

class VectorStoreManager:
    """
    LanceDB 벡터 저장소의 생성, 로드 및 관리를 담당합니다.
    """
    def __init__(
        self,
        db_path: Path = LANCEDB_PATH,
        data_path: Path = DATA_PATH,
        table_name: str = "didimdol_docs",
        embedding_function=None,
    ):
        self.db_path = db_path
        self.data_path = data_path
        self.table_name = table_name
        self.embedding_function = embedding_function or OpenAIEmbeddings(api_key=OPENAI_API_KEY)
        self.db = lancedb.connect(self.db_path)
        self.table = None
        self.vector_store = None
        self.raw_documents: List[Document] = []

    def _load_documents_from_source(self) -> List[Document]:
        """지정된 디렉토리에서 마크다운 문서를 로드합니다."""
        print(f"Loading documents from: {self.data_path}")
        loader = DirectoryLoader(
            path=str(self.data_path),
            glob="**/*.md",
            loader_cls=UnstructuredMarkdownLoader,
            show_progress=True,
            use_multithreading=True,
        )
        return loader.load()

    def _split_documents(self, documents: List[Document]) -> List[Document]:
        """문서를 청크로 분할합니다."""
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
            length_function=len,
        )
        return text_splitter.split_documents(documents)

    def initialize_vector_store(self, force_recreate: bool = False):
        """
        벡터 저장소를 초기화합니다. 기존 테이블이 있고 force_recreate가 False이면 로드하고,
        그렇지 않으면 새로 생성합니다.
        """
        table_names = self.db.table_names()
        if not force_recreate and self.table_name in table_names:
            print(f"Loading existing vector store table: '{self.table_name}'")
            self.table = self.db.open_table(self.table_name)
            self.raw_documents = self._load_documents_from_source() # BM25를 위해 원본 문서 로드
        else:
            print("Creating new vector store table...")
            if self.table_name in table_names:
                self.db.drop_table(self.table_name)
                print(f"Dropped existing table: '{self.table_name}'")

            self.raw_documents = self._load_documents_from_source()
            docs_to_index = self._split_documents(self.raw_documents)
            
            if not docs_to_index:
                raise ValueError("No documents were loaded or split. Cannot create vector store.")
            
            print(f"Creating table '{self.table_name}' with {len(docs_to_index)} document chunks.")
            self.table = self.db.create_table(
                self.table_name,
                data=[
                    {
                        "vector": self.embedding_function.embed_query(doc.page_content),
                        "text": doc.page_content,
                        "source": doc.metadata.get("source", "Unknown"),
                    }
                    for doc in docs_to_index
                ],
                mode="overwrite",
            )
        
        self.vector_store = LanceDB(
            connection=self.db, 
            table_name=self.table_name,
            embedding=self.embedding_function
        )
        print("Vector store initialized successfully.")
        return self

    def get_retriever(self, search_type: str = "hybrid", k: int = 5):
        """하이브리드 또는 벡터 검색을 위한 검색기(retriever)를 반환합니다."""
        if not self.vector_store:
            raise ValueError("Vector store is not initialized.")
        
        vector_retriever = self.vector_store.as_retriever(search_type="similarity", search_kwargs={"k": k})

        if search_type == "hybrid":
            if not self.raw_documents:
                 raise ValueError("Raw documents not loaded, cannot create BM25 retriever.")
            
            # BM25 Retriever는 텍스트 분할이 필요할 수 있습니다. 여기서는 단순화를 위해 전체 문서를 사용합니다.
            text_splitter_for_bm25 = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
            bm25_docs = text_splitter_for_bm25.split_documents(self.raw_documents)
            
            bm25_retriever = BM25Retriever.from_documents(bm25_docs, k=k)
            bm25_retriever.k = k

            ensemble_retriever = EnsembleRetriever(
                retrievers=[bm25_retriever, vector_retriever],
                weights=[0.4, 0.6], # BM25와 Vector 검색의 가중치
            )
            print("Hybrid retriever (BM25 + Vector) created.")
            return ensemble_retriever
        else:
            print("Vector similarity retriever created.")
            return vector_retriever

class RAGPipeline:
    """
    전체 RAG 파이프라인을 관장하는 클래스.
    """
    def __init__(self, retriever, llm):
        self.retriever = retriever
        self.llm = llm
        self.final_answer_synthesizer_prompt = self._get_final_answer_prompt()

    @staticmethod
    def _get_final_answer_prompt():
        prompt_str = """
당신은 제공된 여러 개의 중간 답변들을 종합하여, 최종 사용자에게 제공할 하나의 완결된 답변을 생성하는 AI 비서입니다.

사용자의 원래 질문:
{user_question}

---
아래는 여러 관련 문서 조각과 그에 대한 개별적인 답변입니다. 이 정보들을 바탕으로 종합적인 답변을 만드세요.

{summaries}
---

최종 답변 생성 규칙:
1.  모든 정보를 종합하여 일관성 있고, 논리적이며, 이해하기 쉬운 단일 답변을 작성합니다.
2.  각주나 출처 표기 없이, 자연스러운 문장으로 정보를 전달하세요.
3.  핵심 내용을 명확하게 전달하되, 불필요한 정보나 중복되는 내용은 제거하세요.
4.  "제공된 정보에 따르면", "종합해보면"과 같은 문구는 사용하지 마세요.
5.  부드럽고 친절한 말투를 사용하세요.

종합된 최종 답변:
"""
        return ChatPromptTemplate.from_template(prompt_str)

    async def ainvoke(self, user_questions: List[str], original_question: str) -> RAGOutput:
        """
        사용자 질문 목록에 대한 RAG 파이프라인을 비동기적으로 실행합니다.
        1. 여러 질문으로 동시에 문서 검색
        2. 검색된 문서에서 중복 제거
        3. 최종 답변 종합
        """
        print(f"\n--- RAG Pipeline Started for {len(user_questions)} queries ---")
        print(f"Original question: '{original_question}'")
        print(f"Expanded queries: {user_questions[1:]}")

        # 1. 여러 질문으로 동시에 문서 검색
        tasks = [self.retriever.ainvoke(q) for q in user_questions]
        results_from_all_queries = await asyncio.gather(*tasks)

        # 2. 검색된 문서에서 중복 제거
        unique_docs = {}
        for doc_list in results_from_all_queries:
            for doc in doc_list:
                if doc.page_content not in unique_docs:
                    unique_docs[doc.page_content] = doc
        
        retrieved_docs: List[Document] = list(unique_docs.values())
        print(f"Retrieved {len(retrieved_docs)} unique documents.")
        
        if not retrieved_docs:
            return RAGOutput(
                final_answer="죄송합니다, 관련 정보를 찾을 수 없습니다. 다른 질문을 해주시겠어요?",
                processed_documents=[]
            )

        # 현재는 개별 답변 생성 없이, 검색된 문서 내용을 바로 종합합니다.
        # 추후, 각 문서에 대한 답변을 생성하는 단계를 여기에 추가할 수 있습니다.
        summaries = "\n\n---\n\n".join([f"문서 출처: {doc.metadata.get('source', '알 수 없음')}\n내용: {doc.page_content}" for doc in retrieved_docs])

        # 3. 최종 답변 종합
        synthesis_chain = self.final_answer_synthesizer_prompt | self.llm
        final_response = await synthesis_chain.ainvoke({
            "user_question": original_question, # 최종 답변 생성 시에는 사용자의 원본 질문을 사용
            "summaries": summaries
        })
        
        final_answer = final_response.content.strip()
        print(f"Synthesized Final Answer: {final_answer[:100]}...")

        # 현재 구조에서는 ProcessedDocument를 생성하지 않으므로 빈 리스트로 반환합니다.
        return RAGOutput(final_answer=final_answer, processed_documents=[])

# 스크립트로 직접 실행하여 벡터 저장소를 생성/테스트하기 위한 부분
async def main():
    print("Initializing VectorStoreManager...")
    manager = VectorStoreManager()
    manager.initialize_vector_store(force_recreate=True)
    print("\nVectorStoreManager initialized.")
    
    retriever = manager.get_retriever(search_type="hybrid", k=5)
    print("Retriever created.")

    rag_pipeline = RAGPipeline(retriever=retriever, llm=generative_llm)
    print("RAG Pipeline created.")

    test_question = "디딤돌 대출 금리 알려줘"
    test_queries = [
        test_question, 
        "디딤돌 대출 소득수준별 금리", 
        "디딤돌 대출 우대금리 조건"
    ]
    result = await rag_pipeline.ainvoke(test_queries, original_question=test_question)
    
    print("\n--- RAG Pipeline Test Result ---")
    print(f"Question: {test_question}")
    print(f"Final Answer: {result.final_answer}")
    print("--- End of Test ---")


if __name__ == "__main__":
    import asyncio
    # 'generative_llm'이 이 컨텍스트에서 정의되어 있지 않으므로, 직접 초기화 필요
    from ..graph.chains import generative_llm
    if not generative_llm:
         raise ImportError("Could not import or initialize 'generative_llm'.")
    asyncio.run(main()) 