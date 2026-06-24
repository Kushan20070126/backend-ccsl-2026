import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from ypy_websocket import WebsocketServer


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FastAPIWebsocketAdapter:
    """Adapter wrapping a FastAPI WebSocket to the ypy_websocket Websocket protocol."""

    def __init__(self, websocket: WebSocket, room_name: str):
        self._websocket = websocket
        self._room_name = room_name

    @property
    def path(self) -> str:
        return self._room_name

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        try:
            return await self._websocket.receive_bytes()
        except WebSocketDisconnect:
            raise StopAsyncIteration()
        except Exception:
            raise StopAsyncIteration()

    async def send(self, message: bytes) -> None:
        await self._websocket.send_bytes(message)

    async def recv(self) -> bytes:
        return await self._websocket.receive_bytes()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan event handler for Yjs room lifecycle.
    Initializes a ypy_websocket WebsocketServer on startup and cleans it up on shutdown.
    """
    room_manager = WebsocketServer()
    async with room_manager:
        app.state.room_manager = room_manager
        yield


# Initialize FastAPI app with lifespan handler
app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws/{workspace_id}")
async def websocket_endpoint(websocket: WebSocket, workspace_id: str):
    """
    WebSocket endpoint for collaborative editing sessions.

    Each workspace_id corresponds to a separate Yjs document.

    Connection lifecycle:
      - Accept WebSocket connection
      - Get or create a Yjs room for workspace_id
      - Bridge the FastAPI WebSocket to the ypy_websocket room
      - Keep connection alive until client disconnects
      - Cleanly handle disconnects to prevent log spam
    """
    await websocket.accept()
    room_manager = websocket.app.state.room_manager

    try:
        room = await room_manager.get_room(workspace_id)
        adapter = FastAPIWebsocketAdapter(websocket, workspace_id)
        await room.serve(adapter)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {workspace_id}")
    except Exception as e:
        logger.error(f"WebSocket error for workspace {workspace_id}: {str(e)}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass