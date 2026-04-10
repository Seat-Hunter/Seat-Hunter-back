import json
from fastapi import WebSocket
from collections import defaultdict

class WebSocketManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, session_id: str, ws: WebSocket):
        await ws.accept()
        self._connections[session_id].append(ws)

    def disconnect(self, session_id: str, ws: WebSocket):
        self._connections[session_id].remove(ws)
        if not self._connections[session_id]:
            del self._connections[session_id]

    async def send(self, session_id: str, ws: WebSocket, payload: dict):
        await ws.send_text(json.dumps(payload, ensure_ascii=False))

    async def broadcast(self, session_id: str, payload: dict):
        text = json.dumps(payload, ensure_ascii=False)
        for ws in list(self._connections.get(session_id, [])):
            await ws.send_text(text)

ws_manager = WebSocketManager()