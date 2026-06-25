import logging
import os
import struct
import time
import json
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from websockets.exceptions import ConnectionClosed, ConnectionClosedError, ConnectionClosedOK
from ypy_websocket import WebsocketServer
from ypy_websocket.yroom import YRoom
from ypy_websocket.ystore import BaseYStore, YDocNotFound
from ypy_websocket.yutils import Decoder, write_var_uint

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "20"))
REDIS_SINGLE_CONNECTION = os.getenv("REDIS_SINGLE_CONNECTION", "true").lower() in ("1", "true", "yes")


def workspace_files_key(workspace_id: str) -> str:
    return f"workspace:{workspace_id}:files"


def file_store_key(workspace_id: str, file_id: str) -> str:
    return f"yjs:{workspace_id}:{file_id}"


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
        return RedisYStore(self.redis, file_store_key(*room_name.split(':', 1)) if ':' in room_name else f"yjs:{room_name}")

    async def get_room(self, name: str) -> YRoom:
        if name not in self.rooms:
            room = YRoom(ready=self.rooms_ready, ystore=self._make_store(name), log=self.log)
            try:
                await room.ystore.apply_updates(room.ydoc)
            except YDocNotFound:
                pass
            self.rooms[name] = room
            # FIX 1: start_room() එක call කළ යුත්තේ room එක අලුතින්ම හැදෙන විට (if block එක ඇතුලේ) පමණි.
            # නැතහොත් හැම websocket connection එකකටම අලුත් background persistence tasks බිහි වී conflict ඇතිවේ.
            await self.start_room(room)
        return self.rooms[name]

    async def list_files(self, workspace_id: str) -> list[str]:
        items = await self.redis.smembers(workspace_files_key(workspace_id))
        return [item.decode() if isinstance(item, bytes) else item for item in items]

    async def add_file(self, workspace_id: str, file_id: str) -> None:
        await self.redis.sadd(workspace_files_key(workspace_id), file_id)

    async def remove_file(self, workspace_id: str, file_id: str) -> None:
        await self.redis.srem(workspace_files_key(workspace_id), file_id)
        await self.redis.delete(file_store_key(workspace_id, file_id))


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
        try:
            await self._websocket.send_bytes(message)
        except (WebSocketDisconnect, RuntimeError):
            # Client already disconnected or socket already closed.
            # Swallow this to avoid canceling the room broadcast task group.
            return
        except Exception:
            # Ignore websocket send errors during broadcast; the client will be cleaned up
            # when receive_bytes eventually fails or the task exits.
            return

    async def recv(self) -> bytes:
        try:
            return await self._websocket.receive_bytes()
        except (WebSocketDisconnect, RuntimeError):
            raise ConnectionClosedOK(None, None)
        except Exception as exc:
            raise ConnectionClosedError(None, None) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Redis and the persistent Yjs WebSocket server."""
    redis_client = await redis.from_url(
        REDIS_URL,
        max_connections=REDIS_MAX_CONNECTIONS,
        single_connection_client=REDIS_SINGLE_CONNECTION,
        retry_on_timeout=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    room_manager = RedisWebsocketServer(redis_client)
    async with room_manager:
        app.state.redis = redis_client
        app.state.room_manager = room_manager
        yield
    await redis_client.aclose()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/workspace/{workspace_id}/files")
async def list_workspace_files(workspace_id: str):
    room_manager = app.state.room_manager
    redis_client = room_manager.redis
    
  
    file_ids = await room_manager.list_files(workspace_id)
    
    files = []
    for file_id in file_ids:
        metadata_key = f"workspace:{workspace_id}:file:{file_id}:metadata"
        raw_metadata = await redis_client.get(metadata_key)
        if raw_metadata:
            try:
                files.append(json.loads(raw_metadata.decode() if isinstance(raw_metadata, bytes) else raw_metadata))
            except Exception:
                files.append({
                    "id": file_id,
                    "name": file_id.split('/')[-1],
                    "path": file_id,
                    "content": "",
                    "language": "typescript"
                })
        else:
            files.append({
                "id": file_id,
                "name": file_id.split('/')[-1],
                "path": file_id,
                "content": "",
                "language": "typescript"
            })
    return files


@app.post("/workspace/{workspace_id}/files")
async def create_workspace_file(workspace_id: str, payload: dict):

    file_id = payload.get("path") or payload.get("file_id")
    if not file_id:
        return {"error": "path/file_id is required"}
        
    room_manager = app.state.room_manager
    redis_client = room_manager.redis
    
    await room_manager.add_file(workspace_id, file_id)
    
   
    file_data = {
        "id": file_id,
        "name": payload.get("name") or file_id.split('/')[-1],
        "path": file_id,
        "content": payload.get("content") or "",
        "language": payload.get("language") or "typescript"
    }
    
    metadata_key = f"workspace:{workspace_id}:file:{file_id}:metadata"
    await redis_client.set(metadata_key, json.dumps(file_data))
    
    return file_data


@app.delete("/workspace/{workspace_id}/files/{file_id:path}")
async def delete_workspace_file(workspace_id: str, file_id: str):
    room_manager = app.state.room_manager
    redis_client = room_manager.redis
    
    await room_manager.remove_file(workspace_id, file_id)
    
    # Metadata cleanup
    metadata_key = f"workspace:{workspace_id}:file:{file_id}:metadata"
    await redis_client.delete(metadata_key)
    
    return {"workspace_id": workspace_id, "file_id": file_id, "deleted": True}


@app.websocket("/ws/{workspace_id}/{file_id:path}")
async def websocket_file_endpoint(websocket: WebSocket, workspace_id: str, file_id: str):
    """WebSocket endpoint for collaborative editing on a specific workspace file."""
    await websocket.accept()
    room_manager = websocket.app.state.room_manager
    room_name = f"{workspace_id}:{file_id}"

    try:
        await room_manager.add_file(workspace_id, file_id)
        room = await room_manager.get_room(room_name)
        adapter = FastAPIWebsocketAdapter(websocket, room_name)
        await room.serve(adapter)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {room_name}")
    except Exception as e:
        logger.error(f"WebSocket error for room {room_name}: {str(e)}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


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