"""
WebSocket 연결 관리자
"""

import uuid
from typing import Dict
from fastapi import WebSocket, WebSocketException
from starlette.websockets import WebSocketState


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.websocket_to_session: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket) -> str:
        """WebSocket 연결 및 세션 ID 생성"""
        await websocket.accept()
        session_id = str(uuid.uuid4())
        self.active_connections[session_id] = websocket
        self.websocket_to_session[websocket] = session_id
        print(f"WebSocket connected: {session_id}")
        return session_id

    def disconnect(self, session_id: str):
        """WebSocket 연결 해제"""
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            if websocket in self.websocket_to_session:
                del self.websocket_to_session[websocket]
            del self.active_connections[session_id]
            print(f"WebSocket disconnected: {session_id}")

    def get_session_id(self, websocket: WebSocket) -> str:
        """WebSocket으로부터 세션 ID 조회"""
        return self.websocket_to_session.get(websocket, "")

    async def send_json_to_client(self, session_id: str, data: dict):
        """클라이언트에게 JSON 메시지 전송"""
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            
            # WebSocket 상태 확인
            if websocket.client_state != WebSocketState.CONNECTED:
                print(f"WebSocket not connected for session {session_id}, removing from active connections")
                self.disconnect(session_id)
                return
                
            try:
                await websocket.send_json(data)
            except WebSocketException as e:
                print(f"Error sending to client {session_id} (possibly closed): {e}")
                self.disconnect(session_id)
            except RuntimeError as e:
                # RuntimeError는 주로 이벤트 루프가 닫히거나 WebSocket이 이미 닫힌 경우 발생
                if "Cannot schedule new futures after interpreter shutdown" in str(e):
                    print(f"Interpreter shutting down, cannot send to {session_id}")
                else:
                    print(f"RuntimeError sending to client {session_id}: {e}")
                self.disconnect(session_id)
            except Exception as e:
                print(f"Unexpected error sending to client {session_id}: {type(e).__name__}: {e}")
                self.disconnect(session_id)


manager = ConnectionManager()