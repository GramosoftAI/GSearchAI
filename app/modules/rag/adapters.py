import json
from typing import Protocol
from fastapi import WebSocket
from .events import LoopEvent

class ChannelAdapter(Protocol):
    async def receive(self, websocket: WebSocket) -> dict: ...
    async def send(self, websocket: WebSocket, event: LoopEvent) -> None: ...
    async def send_error(self, websocket: WebSocket, message: str) -> None: ...


class DashboardAdapter:
    async def receive(self, websocket: WebSocket) -> dict:
        # Dashboard sends plain JSON queries over the socket
        # Note: Previous dashboard sent JSON string like {"query": "..."} 
        # The user's snippet said "receive_text()" -> {"query": text}, but if we check the original dashboard code, it receives JSON text and parses it.
        # I will parse the JSON.
        text = await websocket.receive_text()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"query": text} # Fallback if they literally send text

    async def send(self, websocket: WebSocket, event: LoopEvent) -> None:
        if event.type == "token":
            await websocket.send_text(event.text)
        elif event.type == "sources":
            await websocket.send_text(json.dumps({"type": "metadata", "sources": event.sources}))
        elif event.type == "done":
            await websocket.send_text(json.dumps({"type": "done"}))

    async def send_error(self, websocket: WebSocket, message: str) -> None:
        await websocket.send_text(json.dumps({"type": "error", "message": message}))


class EmbedAdapter:
    async def receive(self, websocket: WebSocket) -> dict:
        return await websocket.receive_json()

    async def send(self, websocket: WebSocket, event: LoopEvent) -> None:
        if event.type == "token":
            await websocket.send_json({"type": "content", "delta": event.text})
        elif event.type == "sources":
            await websocket.send_json({"type": "sources", "sources": event.sources})
        elif event.type == "done":
            await websocket.send_json({"type": "done"})

    async def send_error(self, websocket: WebSocket, message: str) -> None:
        await websocket.send_json({"type": "error", "delta": message})
