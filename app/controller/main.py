import logging
import os
import struct
import time
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from ypy_websocket import WebsocketServer
from ypy_websocket.yroom import YRoom
from ypy_websocket.ystore import BaseYStore, YDocNotFound
from ypy_websocket.yutils import Decoder, write_var_uint


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


class RedisYStore(BaseYStore):
    """A Redis-backed Yjs update store."""

    def __init__(self, redis_client: redis.Redis, key: str, metadata_callback=None, log=None):
        self.redis = redis_client
        self.key = key
        self.metadata_callback = metadata_callback
        self.log = log or logging.getLogger(__name__)

    async def write(self, data: bytes) -> None:
        metadata = await self.get_metadata()
        timestamp = struct.pack("<d", time.time())
        payload = write_var_uint(len(data)) + data
        payload += write_var_uint(len(metadata)) + metadata
        payload += write_var_uint(len(timestamp)) + timestamp
        await self.redis.rpush(self.key, payload)

    async def read(self):
        items = await self.redis.lrange(self.key, 0, -1)
        if not items:
            raise YDocNotFound

        for item in items:
            decoder = Decoder(item)
            iterator = decoder.read_messages()
            update = next(iterator)
            metadata = next(iterator)
            timestamp_bytes = next(iterator)
            timestamp = struct.unpack("<d", timestamp_bytes)[0]
            yield update, metadata, timestamp


class RedisWebsocketServer(WebsocketServer):
    """WebsocketServer that creates YRooms with Redis persistence."""

    def __init__(self, redis_client: redis.Redis, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.redis = redis_client

    def _make_store(self, room_name: str) -> RedisYStore:
        return RedisYStore(self.redis, f"yjs:{room_name}")

    async def get_room(self, name: str) -> YRoom:
        if name not in self.rooms:
            room = YRoom(ready=self.rooms_ready, ystore=self._make_store(name), log=self.log)
            try:
                await room.ystore.apply_updates(room.ydoc)
            except YDocNotFound:
                pass
            self.rooms[name] = room
        room = self.rooms[name]
        await self.start_room(room)
        return room


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
    """Initialize Redis and the persistent Yjs WebSocket server."""
    redis_client = await redis.from_url(REDIS_URL)
    room_manager = RedisWebsocketServer(redis_client)
    async with room_manager:
        app.state.redis = redis_client
        app.state.room_manager = room_manager
        yield
    await redis_client.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws/{workspace_id}")
async def websocket_endpoint(websocket: WebSocket, workspace_id: str):
    """WebSocket endpoint for collaborative editing sessions."""
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