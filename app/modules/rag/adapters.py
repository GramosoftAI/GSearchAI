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
        text = await websocket.receive_text()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"query": text}

    async def send(self, websocket: WebSocket, event: LoopEvent) -> None:
        if event.type == "token":
            await websocket.send_text(event.text)
        elif event.type == "sources":
            payload = {"type": "metadata", "sources": event.sources}
            if event.escalation_detected is not None:
                payload["escalation_detected"] = event.escalation_detected
            await websocket.send_text(json.dumps(payload))
        elif event.type == "done":
            payload = {"type": "done"}
            if event.escalation_detected is not None:
                payload["escalation_detected"] = event.escalation_detected
            if event.message_id:
                payload["message_id"] = event.message_id
            await websocket.send_text(json.dumps(payload))

    async def send_error(self, websocket: WebSocket, message: str) -> None:
        await websocket.send_text(json.dumps({"type": "error", "message": message}))


class EmbedAdapter:
    async def receive(self, websocket: WebSocket) -> dict:
        return await websocket.receive_json()

    async def send(self, websocket: WebSocket, event: LoopEvent) -> None:
        if event.type == "token":
            payload = {"type": "content", "delta": event.text}
            if event.escalation_detected is not None:
                payload["escalation_detected"] = event.escalation_detected
            if event.message_id:
                payload["message_id"] = event.message_id
            await websocket.send_json(payload)
        elif event.type == "sources":
            payload = {"type": "sources", "sources": event.sources}
            if event.escalation_detected is not None:
                payload["escalation_detected"] = event.escalation_detected
            await websocket.send_json(payload)
        elif event.type == "done":
            payload = {"type": "done"}
            if event.escalation_detected is not None:
                payload["escalation_detected"] = event.escalation_detected
            if event.message_id:
                payload["message_id"] = event.message_id
            await websocket.send_json(payload)

    async def send_error(self, websocket: WebSocket, message: str) -> None:
        await websocket.send_json({"type": "error", "delta": message})
