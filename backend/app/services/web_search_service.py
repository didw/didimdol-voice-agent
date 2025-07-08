# backend/app/services/web_search_service.py
import os
from tavily import TavilyClient
from typing import List, Dict, Any

class WebSearchService:
    """
    Tavily API를 사용하여 웹 검색을 수행하는 서비스 클래스입니다.
    """
    def __init__(self, api_key: str = None):
        """
        Tavily 클라이언트를 초기화합니다.
        API 키가 제공되지 않으면 환경 변수 'TAVILY_API_KEY'에서 로드합니다.
        """
        api_key = api_key or os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("Tavily API key is not set. Please set the TAVILY_API_KEY environment variable.")
        self.client = TavilyClient(api_key=api_key)

    def _format_results(self, results: List[Dict[str, Any]]) -> str:
        """
        검색 결과를 사람이 읽기 쉬운 문자열로 포맷합니다.
        """
        if not results:
            return "검색 결과가 없습니다."
        
        formatted_string = ""
        for i, result in enumerate(results, 1):
            formatted_string += f"--- Result {i} ---\n"
            formatted_string += f"Title: {result.get('title', 'N/A')}\n"
            formatted_string += f"Source: {result.get('url', 'N/A')}\n"
            formatted_string += f"Content: {result.get('content', 'N/A')}\n\n"
        
        return formatted_string.strip()

    def _format_search_results(self, results: List[Dict[str, Any]]) -> str:
        """
        검색 결과를 테스트에서 기대하는 형식으로 포맷합니다.
        """
        if not results:
            return "검색 결과를 찾을 수 없습니다."
        
        formatted_string = ""
        for result in results:
            title = result.get('title', '')
            url = result.get('url', '')
            content = result.get('content', '')
            
            if title:
                formatted_string += f"{title}\n"
            if url:
                formatted_string += f"URL: {url}\n"
            if content:
                formatted_string += f"{content}\n"
            formatted_string += "\n"
        
        return formatted_string

    async def asearch(self, query: str, max_results: int = 3) -> str:
        """
        주어진 쿼리에 대해 웹 검색을 비동기적으로 수행하고,
        가장 관련성 높은 결과를 요약하여 반환합니다.
        """
        print(f"Performing web search for: '{query}'")
        try:
            # `search` 메소드는 동기적으로 작동하므로, 비동기 컨텍스트에서 직접 호출
            # Tavily 라이브러리가 aiohttp 등을 사용하지 않는 경우, 이 방식이 일반적입니다.
            # 실제 비동기 I/O 바운드 라이브러리를 사용한다면 `await`을 사용합니다.
            response = self.client.search(
                query=query,
                search_depth="advanced", # 더 깊은 분석을 위해 advanced 사용
                max_results=max_results
            )
            
            # 검색 결과에서 URL과 내용을 추출하여 LLM이 요약하도록 전달
            context_for_summary = self._format_results(response.get("results", []))
            
            return context_for_summary

        except Exception as e:
            print(f"An error occurred during web search: {e}")
            return "웹 검색 중 오류가 발생했습니다."

# 어플리케이션 전체에서 공유될 싱글톤 인스턴스
web_search_service = WebSearchService() 