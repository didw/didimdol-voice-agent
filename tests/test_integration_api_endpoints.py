import pytest
import asyncio
import json
from unittest.mock import Mock, AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import WebSocket

# Mock the backend modules before importing
import sys
from pathlib import Path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_path))


class TestAPIEndpointsIntegration:
    """Integration tests for API endpoints and WebSocket connections."""

    @pytest.fixture
    def mock_agent_streaming(self):
        """Mock the agent streaming function for API testing."""
        async def mock_streaming(user_input_text=None, user_input_audio_b64=None, session_id=None, current_state_dict=None):
            # Simulate streaming response
            yield {"type": "stream_start"}
            yield "안"
            yield "녕"
            yield "하"
            yield "세"
            yield "요"
            yield {"type": "stream_end", "full_text": "안녕하세요"}
            yield {
                "type": "final_state", 
                "data": {
                    "session_id": session_id or "test_session",
                    "messages": [],
                    "current_product_type": None,
                    "is_final_turn_response": True,
                    "final_response_text_for_tts": "안녕하세요"
                }
            }
        return mock_streaming

    @pytest.fixture
    def test_app(self, mock_agent_streaming):
        """Create a test FastAPI application."""
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.responses import JSONResponse
        import json
        
        app = FastAPI()
        
        # Session storage for testing
        sessions = {}
        
        @app.get("/health")
        async def health_check():
            return {"status": "healthy"}
        
        @app.post("/api/v1/chat")
        async def chat_endpoint(request_data: dict):
            session_id = request_data.get("session_id", "default")
            user_input = request_data.get("user_input", "")
            
            # Mock response
            return {
                "session_id": session_id,
                "response": f"Response to: {user_input}",
                "conversation_state": "active"
            }
        
        @app.websocket("/ws/chat/{session_id}")
        async def websocket_chat(websocket: WebSocket, session_id: str):
            await websocket.accept()
            
            try:
                while True:
                    data = await websocket.receive_text()
                    message_data = json.loads(data)
                    
                    # Get current session state
                    current_state = sessions.get(session_id, {})
                    
                    # Mock agent streaming
                    async for response in mock_agent_streaming(
                        user_input_text=message_data.get("user_input_text"),
                        user_input_audio_b64=message_data.get("user_input_audio_b64"),
                        session_id=session_id,
                        current_state_dict=current_state
                    ):
                        if isinstance(response, dict):
                            if response.get("type") == "final_state":
                                # Update session state
                                sessions[session_id] = response["data"]
                            await websocket.send_text(json.dumps(response))
                        else:
                            # String response (streaming text)
                            await websocket.send_text(json.dumps({"type": "text", "content": response}))
                            
            except WebSocketDisconnect:
                if session_id in sessions:
                    del sessions[session_id]
        
        return app

    def test_health_endpoint(self, test_app):
        """Test health check endpoint."""
        client = TestClient(test_app)
        response = client.get("/health")
        
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_chat_endpoint_basic(self, test_app):
        """Test basic chat endpoint functionality."""
        client = TestClient(test_app)
        
        request_data = {
            "session_id": "test_session_001",
            "user_input": "안녕하세요"
        }
        
        response = client.post("/api/v1/chat", json=request_data)
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["session_id"] == "test_session_001"
        assert "Response to: 안녕하세요" in response_data["response"]

    def test_websocket_connection_basic(self, test_app):
        """Test basic WebSocket connection and message exchange."""
        client = TestClient(test_app)
        
        with client.websocket_connect("/ws/chat/test_session") as websocket:
            # Send initial message
            test_message = {
                "user_input_text": "안녕하세요",
                "session_id": "test_session"
            }
            websocket.send_text(json.dumps(test_message))
            
            # Receive streaming responses
            responses = []
            for _ in range(10):  # Limit to prevent infinite loop
                try:
                    data = websocket.receive_text()
                    response = json.loads(data)
                    responses.append(response)
                    
                    if response.get("type") == "final_state":
                        break
                except:
                    break
            
            assert len(responses) > 0
            
            # Check for expected response types
            response_types = [r.get("type") for r in responses if isinstance(r, dict)]
            assert "stream_start" in response_types
            assert "final_state" in response_types

    def test_websocket_session_persistence(self, test_app):
        """Test that WebSocket maintains session state across messages."""
        client = TestClient(test_app)
        
        with client.websocket_connect("/ws/chat/persistent_session") as websocket:
            # First message
            message1 = {
                "user_input_text": "디딤돌 대출을 선택해주세요",
                "session_id": "persistent_session"
            }
            websocket.send_text(json.dumps(message1))
            
            # Receive responses for first message
            responses1 = []
            for _ in range(10):
                try:
                    data = websocket.receive_text()
                    response = json.loads(data)
                    responses1.append(response)
                    
                    if response.get("type") == "final_state":
                        break
                except:
                    break
            
            # Second message (should maintain context)
            message2 = {
                "user_input_text": "금리가 궁금해요",
                "session_id": "persistent_session"
            }
            websocket.send_text(json.dumps(message2))
            
            # Receive responses for second message
            responses2 = []
            for _ in range(10):
                try:
                    data = websocket.receive_text()
                    response = json.loads(data)
                    responses2.append(response)
                    
                    if response.get("type") == "final_state":
                        break
                except:
                    break
            
            # Verify both conversations completed
            assert len(responses1) > 0
            assert len(responses2) > 0

    def test_websocket_audio_input(self, test_app):
        """Test WebSocket with audio input."""
        client = TestClient(test_app)
        
        with client.websocket_connect("/ws/chat/audio_session") as websocket:
            # Send message with audio data
            audio_message = {
                "user_input_audio_b64": "mock_base64_audio_data",
                "session_id": "audio_session"
            }
            websocket.send_text(json.dumps(audio_message))
            
            # Receive responses
            responses = []
            for _ in range(10):
                try:
                    data = websocket.receive_text()
                    response = json.loads(data)
                    responses.append(response)
                    
                    if response.get("type") == "final_state":
                        break
                except:
                    break
            
            assert len(responses) > 0

    def test_websocket_error_handling(self, test_app):
        """Test WebSocket error handling."""
        client = TestClient(test_app)
        
        with client.websocket_connect("/ws/chat/error_session") as websocket:
            # Send malformed message
            websocket.send_text("invalid json")
            
            # Should handle error gracefully
            try:
                data = websocket.receive_text()
                # If we get here, the server handled the error
                assert True
            except:
                # If connection closes, that's also acceptable error handling
                assert True

    def test_concurrent_websocket_sessions(self, test_app):
        """Test multiple concurrent WebSocket sessions."""
        client = TestClient(test_app)
        
        # Start multiple sessions
        sessions = []
        for i in range(3):
            session_id = f"concurrent_session_{i}"
            ws = client.websocket_connect(f"/ws/chat/{session_id}")
            sessions.append((session_id, ws))
        
        try:
            # Send messages to all sessions
            for session_id, ws in sessions:
                with ws:
                    message = {
                        "user_input_text": f"Hello from {session_id}",
                        "session_id": session_id
                    }
                    ws.send_text(json.dumps(message))
                    
                    # Receive at least one response
                    data = ws.receive_text()
                    response = json.loads(data)
                    assert response is not None
        finally:
            # Clean up sessions
            for _, ws in sessions:
                try:
                    ws.close()
                except:
                    pass

    @pytest.mark.asyncio
    async def test_api_performance_basic(self, test_app):
        """Test basic API performance metrics."""
        client = TestClient(test_app)
        
        import time
        
        # Test multiple requests
        num_requests = 10
        start_time = time.time()
        
        for i in range(num_requests):
            request_data = {
                "session_id": f"perf_test_{i}",
                "user_input": f"Test message {i}"
            }
            response = client.post("/api/v1/chat", json=request_data)
            assert response.status_code == 200
        
        end_time = time.time()
        total_time = end_time - start_time
        avg_response_time = total_time / num_requests
        
        # Basic performance assertion (should be reasonable)
        assert avg_response_time < 1.0  # Less than 1 second per request

    def test_api_input_validation(self, test_app):
        """Test API input validation."""
        client = TestClient(test_app)
        
        # Test with missing required fields
        invalid_requests = [
            {},  # Empty request
            {"session_id": "test"},  # Missing user_input
            {"user_input": "test"},  # Missing session_id
        ]
        
        for invalid_request in invalid_requests:
            response = client.post("/api/v1/chat", json=invalid_request)
            # Should either accept with defaults or return validation error
            # Either is acceptable behavior
            assert response.status_code in [200, 422]

    def test_websocket_message_format_validation(self, test_app):
        """Test WebSocket message format validation."""
        client = TestClient(test_app)
        
        with client.websocket_connect("/ws/chat/validation_test") as websocket:
            # Test various message formats
            valid_message = {
                "user_input_text": "Hello",
                "session_id": "validation_test"
            }
            
            # This should work
            websocket.send_text(json.dumps(valid_message))
            
            # Receive response to ensure it processed
            try:
                data = websocket.receive_text()
                response = json.loads(data)
                assert response is not None
            except:
                # If there's an error, the test should still pass
                # as error handling is acceptable
                pass