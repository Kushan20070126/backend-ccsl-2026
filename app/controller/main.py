import os
import logging
import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from ypy_websocket import RedisRoom
from ypy_websocket.asgiprovider import WebSocketsProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


class RedisRoomManager:
    """
    Manages Redis rooms for Yjs document synchronization.
    Each workspace gets its own Redis room for broadcasting Yjs updates.
    """
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.redis_client = None

    async def start(self):
        """Initialize Redis connection pool on startup."""
        self.redis_client = await redis.from_url(self.redis_url)
        logger.info(f"Connected to Redis at {self.redis_url}")

    async def stop(self):
        """Close Redis connection pool on shutdown."""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Disconnected from Redis")

    def get_room(self, room_name: str) -> RedisRoom:
        """
        Get or create a Redis room for the given workspace ID.
        Each workspace gets isolated Yjs document collaboration.
        """
        return RedisRoom(self.redis_client, room_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan event handler for managing Redis connection lifecycle.
    Initializes RedisRoomManager on startup and cleans up on shutdown.
    """
    room_manager = RedisRoomManager(REDIS_URL)
    await room_manager.start()
    app.state.room_manager = room_manager
    yield
    await room_manager.stop()


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
    Binary Yjs delta states flow through Redis:
      1. Client sends binary update via WebSocket
      2. WebSocketsProvider publishes update to Redis channel for workspace_id
      3. Redis publishes to all subscribers of that channel
      4. WebSocketsProvider delivers updates to all connected clients
      5. Clients apply updates to their local Yjs document (CRDT)
    
    Connection lifecycle:
      - Accept WebSocket connection
      - Get RedisRoom for workspace_id
      - Wrap connection in WebSocketsProvider for Yjs sync
      - Keep connection alive until client disconnects
      - Cleanly handle disconnects to prevent log spam
    """
    await websocket.accept()
    room_manager = websocket.app.state.room_manager
    
    try:
        # Get Redis room for this workspace (creates if new)
        room = room_manager.get_room(workspace_id)
        
        # Bridge WebSocket events to Yjs document via Redis
        async with WebSocketsProvider(websocket, room) as provider:
            # Keep connection alive and handle incoming messages
            # WebSocketsProvider handles Yjs sync internally
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass
    except WebSocketDisconnect:
        # Handle disconnect during connection acceptance
        logger.info(f"WebSocket disconnected during acceptance: {workspace_id}")
    except Exception as e:
        logger.error(f"WebSocket error for workspace {workspace_id}: {str(e)}")
    finally:
        # Ensure clean disconnection
        try:
            await websocket.close()
        except Exception:
            pass