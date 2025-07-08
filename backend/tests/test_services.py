import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json
import base64
from pathlib import Path

from app.services.rag_service import RAGService
from app.services.web_search_service import WebSearchService


class TestRAGService:
    """Test cases for RAGService class."""

    @pytest.fixture
    def mock_rag_pipeline(self):
        """Create a mock RAG pipeline."""
        mock_pipeline = AsyncMock()
        mock_pipeline.ainvoke = AsyncMock()
        return mock_pipeline

    @pytest.fixture
    def rag_service_instance(self, mock_rag_pipeline):
        """Create a RAGService instance with mocked dependencies."""
        service = RAGService()
        service.rag_pipeline = mock_rag_pipeline
        service._ready = True
        return service

    def test_rag_service_singleton(self):
        """Test that RAGService is a singleton."""
        service1 = RAGService()
        service2 = RAGService()
        
        assert service1 is service2

    def test_rag_service_is_ready_false_initially(self):
        """Test that RAGService is not ready initially."""
        service = RAGService()
        service._ready = False
        
        assert not service.is_ready()

    def test_rag_service_is_ready_true_when_initialized(self, rag_service_instance):
        """Test that RAGService is ready when properly initialized."""
        assert rag_service_instance.is_ready()

    @pytest.mark.asyncio
    async def test_answer_question_success(self, rag_service_instance, mock_rag_pipeline):
        """Test successful question answering."""
        from app.rag.models import RAGOutput
        
        mock_output = RAGOutput(
            final_answer="디딤돌 대출은 청년층을 위한 정부 지원 대출입니다.",
            processed_documents=[]
        )
        mock_rag_pipeline.ainvoke.return_value = mock_output
        
        queries = ["디딤돌 대출이란?"]
        original_question = "디딤돌 대출이란?"
        
        result = await rag_service_instance.answer_question(queries, original_question)
        
        assert result == "디딤돌 대출은 청년층을 위한 정부 지원 대출입니다."
        mock_rag_pipeline.ainvoke.assert_called_once_with(queries, original_question)

    @pytest.mark.asyncio
    async def test_answer_question_not_ready(self):
        """Test answer_question when service is not ready."""
        service = RAGService()
        service._ready = False
        
        result = await service.answer_question(["test"], "test")
        
        assert "RAG 서비스가 초기화되지 않았습니다" in result

    @pytest.mark.asyncio
    async def test_answer_question_pipeline_error(self, rag_service_instance, mock_rag_pipeline):
        """Test answer_question when pipeline raises an error."""
        mock_rag_pipeline.ainvoke.side_effect = Exception("Pipeline Error")
        
        result = await rag_service_instance.answer_question(["test"], "test")
        
        assert "RAG 처리 중 오류가 발생했습니다" in result

    @patch('app.services.rag_service.VectorStoreManager')
    @patch('app.services.rag_service.RAGPipeline')
    @patch('app.services.rag_service.generative_llm')
    @pytest.mark.asyncio
    async def test_initialize_success(self, mock_llm, mock_pipeline_class, mock_manager_class):
        """Test successful RAG service initialization."""
        mock_manager = Mock()
        mock_manager.initialize_vector_store.return_value = mock_manager
        mock_manager.get_retriever.return_value = Mock()
        mock_manager_class.return_value = mock_manager
        
        mock_pipeline = Mock()
        mock_pipeline_class.return_value = mock_pipeline
        
        service = RAGService()
        await service.initialize()
        
        assert service.is_ready() is True
        assert service.rag_pipeline == mock_pipeline
        mock_manager.initialize_vector_store.assert_called_once()
        mock_manager.get_retriever.assert_called_once()

    @patch('app.services.rag_service.VectorStoreManager')
    @pytest.mark.asyncio
    async def test_initialize_failure(self, mock_manager_class):
        """Test RAG service initialization failure."""
        mock_manager_class.side_effect = Exception("Initialization Error")
        
        service = RAGService()
        with pytest.raises(Exception):
            await service.initialize()
        
        assert service.is_ready() is False
        assert service.rag_pipeline is None


class TestWebSearchService:
    """Test cases for WebSearchService class."""

    @pytest.fixture
    def web_search_service(self):
        """Create a WebSearchService instance."""
        return WebSearchService()

    @patch('app.services.web_search_service.TavilySearchAPIWrapper')
    def test_web_search_service_init(self, mock_tavily, web_search_service):
        """Test WebSearchService initialization."""
        assert web_search_service.search_engine is not None

    @pytest.mark.asyncio
    @patch('app.services.web_search_service.TavilySearchAPIWrapper')
    async def test_asearch_success(self, mock_tavily_class, web_search_service):
        """Test successful web search."""
        mock_tavily = Mock()
        mock_results = [
            {"title": "제목1", "url": "http://example1.com", "content": "내용1"},
            {"title": "제목2", "url": "http://example2.com", "content": "내용2"}
        ]
        mock_tavily.results.return_value = mock_results
        mock_tavily_class.return_value = mock_tavily
        
        # Re-initialize service to use mocked Tavily
        service = WebSearchService()
        
        result = await service.asearch("테스트 검색")
        
        expected_result = (
            "제목1\nURL: http://example1.com\n내용1\n\n"
            "제목2\nURL: http://example2.com\n내용2\n\n"
        )
        assert result == expected_result
        mock_tavily.results.assert_called_once_with("테스트 검색", max_results=5)

    @pytest.mark.asyncio
    @patch('app.services.web_search_service.TavilySearchAPIWrapper')
    async def test_asearch_no_results(self, mock_tavily_class, web_search_service):
        """Test web search with no results."""
        mock_tavily = Mock()
        mock_tavily.results.return_value = []
        mock_tavily_class.return_value = mock_tavily
        
        service = WebSearchService()
        
        result = await service.asearch("존재하지 않는 검색")
        
        assert result == "검색 결과를 찾을 수 없습니다."

    @pytest.mark.asyncio
    @patch('app.services.web_search_service.TavilySearchAPIWrapper')
    async def test_asearch_error(self, mock_tavily_class, web_search_service):
        """Test web search with error."""
        mock_tavily = Mock()
        mock_tavily.results.side_effect = Exception("Search Error")
        mock_tavily_class.return_value = mock_tavily
        
        service = WebSearchService()
        
        result = await service.asearch("오류 검색")
        
        assert "웹 검색 중 오류가 발생했습니다" in result

    @pytest.mark.asyncio
    @patch('app.services.web_search_service.TavilySearchAPIWrapper')
    async def test_asearch_custom_max_results(self, mock_tavily_class, web_search_service):
        """Test web search with custom max_results."""
        mock_tavily = Mock()
        mock_results = [{"title": "제목", "url": "http://example.com", "content": "내용"}]
        mock_tavily.results.return_value = mock_results
        mock_tavily_class.return_value = mock_tavily
        
        service = WebSearchService()
        
        await service.asearch("테스트", max_results=10)
        
        mock_tavily.results.assert_called_once_with("테스트", max_results=10)

    def test_format_search_results_empty(self, web_search_service):
        """Test formatting empty search results."""
        result = web_search_service._format_search_results([])
        
        assert result == "검색 결과를 찾을 수 없습니다."

    def test_format_search_results_with_data(self, web_search_service):
        """Test formatting search results with data."""
        results = [
            {"title": "제목1", "url": "http://example1.com", "content": "내용1"},
            {"title": "제목2", "url": "http://example2.com", "content": "내용2"}
        ]
        
        result = web_search_service._format_search_results(results)
        
        expected = (
            "제목1\nURL: http://example1.com\n내용1\n\n"
            "제목2\nURL: http://example2.com\n내용2\n\n"
        )
        assert result == expected

    def test_format_search_results_missing_fields(self, web_search_service):
        """Test formatting search results with missing fields."""
        results = [
            {"title": "제목만 있음"},
            {"url": "http://example.com", "content": "URL과 내용만 있음"},
            {}  # 모든 필드 누락
        ]
        
        result = web_search_service._format_search_results(results)
        
        # Should handle missing fields gracefully
        assert "제목만 있음" in result
        assert "http://example.com" in result
        assert "URL과 내용만 있음" in result