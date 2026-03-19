"""WebSocket handlers for debate sessions."""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.routes.debate import DebateSession, safe_send_message
from api.state import active_debates, metrics

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Enhanced WebSocket connection management."""
    client_id = str(uuid.uuid4())[:8]
    connection_time = asyncio.get_event_loop().time()

    try:
        await websocket.accept()
        logger.info("WebSocket connected: %s -> %s", client_id, session_id)

        metrics.record_connection_change(1)

        if session_id not in active_debates:
            await websocket.close(code=1008, reason="Invalid session")
            logger.warning("Invalid session: %s", session_id)
            metrics.record_connection_change(-1)
            return

        session = active_debates[session_id]
        session.clients.append(websocket)

        await safe_send_message(
            websocket,
            {
                "type": "connection_confirmed",
                "data": {
                    "client_id": client_id,
                    "session_id": session_id,
                    "server_time": connection_time * 1000,
                    "status": "connected",
                },
            },
        )

        heartbeat_task = asyncio.create_task(
            heartbeat_manager(websocket, client_id)
        )

        try:
            while True:
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(), timeout=30.0
                    )

                    await handle_client_message(
                        websocket, session, data, client_id
                    )

                except asyncio.TimeoutError:
                    logger.debug("Heartbeat check: %s", client_id)
                    continue

                except WebSocketDisconnect:
                    logger.info("Client disconnected: %s", client_id)
                    break

        except Exception as e:
            logger.error("WebSocket error: %s - %s", client_id, e)

        finally:
            heartbeat_task.cancel()
            if websocket in session.clients:
                session.clients.remove(websocket)

            logger.info("Client cleanup complete: %s", client_id)

            if not session.clients and session_id in active_debates:
                logger.info("Empty session cleanup: %s", session_id)
                del active_debates[session_id]

    except Exception as e:
        logger.error("WebSocket connection failed: %s - %s", client_id, e)
        try:
            await websocket.close(code=1011, reason="Server error")
        except Exception:
            pass


async def heartbeat_manager(websocket: WebSocket, client_id: str) -> None:
    """Heartbeat management for WebSocket connections."""
    try:
        while True:
            await asyncio.sleep(15)

            await safe_send_message(
                websocket,
                {
                    "type": "heartbeat",
                    "data": {
                        "client_id": client_id,
                        "timestamp": asyncio.get_event_loop().time() * 1000,
                    },
                },
            )

    except asyncio.CancelledError:
        logger.debug("Heartbeat stopped: %s", client_id)
    except Exception as e:
        logger.error("Heartbeat error: %s - %s", client_id, e)


async def handle_client_message(
    websocket: WebSocket, session: DebateSession, data: str, client_id: str
) -> None:
    """Process incoming client messages."""
    try:
        message = json.loads(data)
        message_type = message.get("type")

        if message_type == "ping":
            await safe_send_message(
                websocket,
                {
                    "type": "pong",
                    "data": {
                        "client_id": client_id,
                        "timestamp": asyncio.get_event_loop().time() * 1000,
                    },
                },
            )

        elif message_type == "sync_request":
            await handle_sync_request(
                websocket, session, message.get("data"), client_id
            )

        else:
            logger.debug("Unknown message type: %s from %s", message_type, client_id)

    except json.JSONDecodeError:
        logger.warning("Invalid JSON from client: %s", client_id)
    except Exception as e:
        logger.error("Message handling error: %s - %s", client_id, e)


async def handle_sync_request(
    websocket: WebSocket, session: DebateSession, data: dict, client_id: str
) -> None:
    """Handle state synchronization requests."""
    try:
        await safe_send_message(
            websocket,
            {
                "type": "sync_response",
                "data": {
                    "current_round": session.current_round,
                    "is_active": session.is_active,
                    "session_id": session.session_id,
                    "client_id": client_id,
                    "server_time": asyncio.get_event_loop().time() * 1000,
                },
            },
        )
        logger.debug("Sync response sent: %s", client_id)

    except Exception as e:
        logger.error("Sync response failed: %s - %s", client_id, e)
