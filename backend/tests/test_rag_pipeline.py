import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path
import tempfile
import lancedb
from langchain_core.documents import Document

from app.rag.rag_pipeline import VectorStoreManager, RAGPipeline
from app.rag.models import RAGOutput


class TestVectorStoreManager:
    """Test cases for VectorStoreManager class."""

    def test_vector_store_manager_init(self, temp_data_dir):
        """Test VectorStoreManager initialization."""
        manager = VectorStoreManager(
            db_path=Path(temp_data_dir) / ".lancedb",
            data_path=Path(temp_data_dir)
        )
        
        assert manager.db_path == Path(temp_data_dir) / ".lancedb"
        assert manager.data_path == Path(temp_data_dir)
        assert manager.table_name == "didimdol_docs"
        assert manager.embedding_function is not None

    @patch('app.rag.rag_pipeline.DirectoryLoader')
    def test_load_documents_from_source(self, mock_loader, temp_data_dir):
        """Test document loading from source directory."""
        manager = VectorStoreManager(data_path=Path(temp_data_dir))
        
        mock_documents = [
            Document(page_content="Test content 1", metadata={"source": "test1.md"}),
            Document(page_content="Test content 2", metadata={"source": "test2.md"})
        ]
        
        mock_loader_instance = Mock()
        mock_loader_instance.load.return_value = mock_documents
        mock_loader.return_value = mock_loader_instance
        
        result = manager._load_documents_from_source()
        
        assert len(result) == 2
        assert result[0].page_content == "Test content 1"
        mock_loader.assert_called_once()

    def test_split_documents(self, temp_data_dir):
        """Test document splitting functionality."""
        manager = VectorStoreManager(data_path=Path(temp_data_dir))
        
        documents = [
            Document(
                page_content="A" * 2000,  # Large content that should be split
                metadata={"source": "test.md"}
            )
        ]
        
        result = manager._split_documents(documents)
        
        assert len(result) > 1  # Should be split into multiple chunks
        assert all(isinstance(doc, Document) for doc in result)
        assert all(len(doc.page_content) <= 1000 for doc in result)

    @patch('app.rag.rag_pipeline.lancedb.connect')
    @patch.object(VectorStoreManager, '_load_documents_from_source')
    @patch.object(VectorStoreManager, '_split_documents')
    def test_initialize_vector_store_create_new(self, mock_split, mock_load, mock_connect, temp_data_dir):
        """Test creating new vector store."""
        mock_db = Mock()
        mock_db.table_names.return_value = []
        mock_connect.return_value = mock_db
        
        mock_documents = [Document(page_content="Test", metadata={"source": "test.md"})]
        mock_load.return_value = mock_documents
        mock_split.return_value = mock_documents
        
        mock_table = Mock()
        mock_db.create_table.return_value = mock_table
        
        mock_embedding = Mock()
        mock_embedding.embed_query.return_value = [0.1, 0.2, 0.3]
        
        manager = VectorStoreManager(
            db_path=Path(temp_data_dir) / ".lancedb",
            data_path=Path(temp_data_dir),
            embedding_function=mock_embedding
        )
        
        with patch('app.rag.rag_pipeline.LanceDB') as mock_lancedb:
            result = manager.initialize_vector_store(force_recreate=True)
            
            assert result == manager
            mock_db.create_table.assert_called_once()
            mock_lancedb.assert_called_once()

    @patch('app.rag.rag_pipeline.lancedb.connect')
    @patch.object(VectorStoreManager, '_load_documents_from_source')
    def test_initialize_vector_store_load_existing(self, mock_load, mock_connect, temp_data_dir):
        """Test loading existing vector store."""
        mock_db = Mock()
        mock_db.table_names.return_value = ["didimdol_docs"]
        mock_connect.return_value = mock_db
        
        mock_table = Mock()
        mock_db.open_table.return_value = mock_table
        
        mock_documents = [Document(page_content="Test", metadata={"source": "test.md"})]
        mock_load.return_value = mock_documents
        
        manager = VectorStoreManager(
            db_path=Path(temp_data_dir) / ".lancedb",
            data_path=Path(temp_data_dir)
        )
        
        with patch('app.rag.rag_pipeline.LanceDB') as mock_lancedb:
            result = manager.initialize_vector_store(force_recreate=False)
            
            assert result == manager
            mock_db.open_table.assert_called_once_with("didimdol_docs")
            mock_lancedb.assert_called_once()

    def test_get_retriever_vector_only(self, temp_data_dir):
        """Test getting vector-only retriever."""
        manager = VectorStoreManager(data_path=Path(temp_data_dir))
        
        mock_vector_store = Mock()
        mock_retriever = Mock()
        mock_vector_store.as_retriever.return_value = mock_retriever
        manager.vector_store = mock_vector_store
        
        result = manager.get_retriever(search_type="vector", k=5)
        
        assert result == mock_retriever
        mock_vector_store.as_retriever.assert_called_once_with(
            search_type="similarity", 
            search_kwargs={"k": 5}
        )

    @patch('app.rag.rag_pipeline.BM25Retriever')
    @patch('app.rag.rag_pipeline.EnsembleRetriever')
    def test_get_retriever_hybrid(self, mock_ensemble, mock_bm25, temp_data_dir):
        """Test getting hybrid retriever."""
        manager = VectorStoreManager(data_path=Path(temp_data_dir))
        
        mock_vector_store = Mock()
        mock_vector_retriever = Mock()
        mock_vector_store.as_retriever.return_value = mock_vector_retriever
        manager.vector_store = mock_vector_store
        
        mock_documents = [Document(page_content="Test", metadata={"source": "test.md"})]
        manager.raw_documents = mock_documents
        
        mock_bm25_retriever = Mock()
        mock_bm25.from_documents.return_value = mock_bm25_retriever
        
        mock_ensemble_retriever = Mock()
        mock_ensemble.return_value = mock_ensemble_retriever
        
        result = manager.get_retriever(search_type="hybrid", k=5)
        
        assert result == mock_ensemble_retriever
        mock_bm25.from_documents.assert_called_once()
        mock_ensemble.assert_called_once()

    def test_get_retriever_not_initialized(self, temp_data_dir):
        """Test getting retriever when vector store is not initialized."""
        manager = VectorStoreManager(data_path=Path(temp_data_dir))
        manager.vector_store = None
        
        with pytest.raises(ValueError, match="Vector store is not initialized"):
            manager.get_retriever()


class TestRAGPipeline:
    """Test cases for RAGPipeline class."""

    def test_rag_pipeline_init(self):
        """Test RAGPipeline initialization."""
        mock_retriever = Mock()
        mock_llm = Mock()
        
        pipeline = RAGPipeline(retriever=mock_retriever, llm=mock_llm)
        
        assert pipeline.retriever == mock_retriever
        assert pipeline.llm == mock_llm
        assert pipeline.final_answer_synthesizer_prompt is not None

    @pytest.mark.asyncio
    async def test_rag_pipeline_ainvoke_success(self):
        """Test successful RAG pipeline execution."""
        mock_retriever = AsyncMock()
        mock_retriever.ainvoke.return_value = [
            Document(page_content="디딤돌 대출 정보", metadata={"source": "didimdol.md"}),
            Document(page_content="금리 정보", metadata={"source": "rates.md"})
        ]
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = "디딤돌 대출은 청년층을 위한 정부 지원 대출입니다."
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        pipeline = RAGPipeline(retriever=mock_retriever, llm=mock_llm)
        
        user_questions = ["디딤돌 대출이란?", "디딤돌 대출 금리"]
        original_question = "디딤돌 대출이란?"
        
        result = await pipeline.ainvoke(user_questions, original_question)
        
        assert isinstance(result, RAGOutput)
        assert result.final_answer == "디딤돌 대출은 청년층을 위한 정부 지원 대출입니다."
        assert result.processed_documents == []
        
        # Check that retriever was called for each question
        assert mock_retriever.ainvoke.call_count == len(user_questions)

    @pytest.mark.asyncio
    async def test_rag_pipeline_ainvoke_no_documents(self):
        """Test RAG pipeline when no documents are retrieved."""
        mock_retriever = AsyncMock()
        mock_retriever.ainvoke.return_value = []
        
        mock_llm = Mock()
        
        pipeline = RAGPipeline(retriever=mock_retriever, llm=mock_llm)
        
        user_questions = ["존재하지 않는 질문"]
        original_question = "존재하지 않는 질문"
        
        result = await pipeline.ainvoke(user_questions, original_question)
        
        assert isinstance(result, RAGOutput)
        assert "관련 정보를 찾을 수 없습니다" in result.final_answer
        assert result.processed_documents == []

    @pytest.mark.asyncio
    async def test_rag_pipeline_ainvoke_duplicate_removal(self):
        """Test that RAG pipeline removes duplicate documents."""
        duplicate_doc = Document(page_content="중복 내용", metadata={"source": "test.md"})
        unique_doc = Document(page_content="고유 내용", metadata={"source": "test2.md"})
        
        mock_retriever = AsyncMock()
        # First query returns duplicate_doc, second query returns both
        mock_retriever.ainvoke.side_effect = [
            [duplicate_doc],
            [duplicate_doc, unique_doc]
        ]
        
        mock_llm = AsyncMock()
        mock_response = Mock()
        mock_response.content = "종합된 답변입니다."
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        
        pipeline = RAGPipeline(retriever=mock_retriever, llm=mock_llm)
        
        user_questions = ["질문1", "질문2"]
        original_question = "질문1"
        
        result = await pipeline.ainvoke(user_questions, original_question)
        
        # LLM should be called with only unique documents
        mock_llm.ainvoke.assert_called_once()
        call_args = mock_llm.ainvoke.call_args[0][0]
        
        # Check that summaries contain both unique documents
        assert "중복 내용" in call_args["summaries"]
        assert "고유 내용" in call_args["summaries"]
        # But "중복 내용" should appear only once
        assert call_args["summaries"].count("중복 내용") == 1

    @pytest.mark.asyncio
    async def test_rag_pipeline_ainvoke_llm_error(self):
        """Test RAG pipeline when LLM fails."""
        mock_retriever = AsyncMock()
        mock_retriever.ainvoke.return_value = [
            Document(page_content="테스트 내용", metadata={"source": "test.md"})
        ]
        
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM Error"))
        
        pipeline = RAGPipeline(retriever=mock_retriever, llm=mock_llm)
        
        user_questions = ["테스트 질문"]
        original_question = "테스트 질문"
        
        with pytest.raises(Exception):
            await pipeline.ainvoke(user_questions, original_question)

    def test_final_answer_prompt_template(self):
        """Test final answer prompt template creation."""
        mock_retriever = Mock()
        mock_llm = Mock()
        
        pipeline = RAGPipeline(retriever=mock_retriever, llm=mock_llm)
        
        prompt = pipeline.final_answer_synthesizer_prompt
        
        # Check that the prompt template has the expected input variables
        assert "user_question" in prompt.input_variables
        assert "summaries" in prompt.input_variables
        
        # Test prompt formatting
        formatted = prompt.format(
            user_question="테스트 질문",
            summaries="테스트 요약"
        )
        
        assert "테스트 질문" in formatted
        assert "테스트 요약" in formatted