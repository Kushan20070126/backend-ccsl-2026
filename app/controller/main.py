import logging
import os
import struct
import time
import json
import secrets
from contextlib import asynccontextmanager
from typing import Dict, Any

from dotenv import load_dotenv
load_dotenv()

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
from ypy_websocket import WebsocketServer
from ypy_websocket.yroom import YRoom
from ypy_websocket.ystore import BaseYStore, YDocNotFound
from ypy_websocket.yutils import Decoder, write_var_uint

# Logging Configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Redis Env Variables
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "20"))
REDIS_SINGLE_CONNECTION = os.getenv("REDIS_SINGLE_CONNECTION", "true").lower() in ("1", "true", "yes")

# MongoDB Env Variables
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://admin@localhost:27017/?authSource=admin")
DATABASE_NAME = os.getenv("DATABASE_NAME", "collab_editor")


def workspace_files_key(workspace_id: str) -> str:
    return f"workspace:{workspace_id}:files"


def file_store_key(workspace_id: str, file_id: str) -> str:
    return f"yjs:{workspace_id}:{file_id}"


class RedisYStore(BaseYStore):
    """A Redis-backed Yjs update cache store."""

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
    """WebsocketServer that creates YRooms with Redis persistence cache."""

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
            await self.start_room(room)
        return self.rooms[name]

    async def remove_file(self, workspace_id: str, file_id: str) -> None:
        """Removes the file key from Redis cache."""
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
            return
        except Exception:
            return

    async def recv(self) -> bytes:
        try:
            return await self._websocket.receive_bytes()
        except (WebSocketDisconnect, RuntimeError):
            raise ConnectionClosedOK(None, None)
        except Exception as exc:
            raise ConnectionClosedError(None, None) from exc


# Lifespan context to handle both Redis and MongoDB
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize Redis and MongoDB connections."""
    logger.info("Connecting to Redis...")
    redis_client = await redis.from_url(
        REDIS_URL,
        max_connections=REDIS_MAX_CONNECTIONS,
        single_connection_client=REDIS_SINGLE_CONNECTION,
        retry_on_timeout=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )
    
    logger.info("Connecting to MongoDB...")
    mongo_client = AsyncIOMotorClient(MONGODB_URL)
    
    room_manager = RedisWebsocketServer(redis_client)
    
    async with room_manager:
        app.state.redis = redis_client
        app.state.mongo_client = mongo_client
        app.state.db = mongo_client[DATABASE_NAME]
        app.state.room_manager = room_manager
        yield
        
    await redis_client.aclose()
    mongo_client.close()
    logger.info("Connections closed.")


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Helper function to check passcode for private workspaces
async def verify_workspace_access(workspace_id: str, passcode: str = None) -> Dict[str, Any]:
    db = app.state.db
    workspace = await db.workspaces.find_one({"workspace_id": workspace_id})
    
    if not workspace:
        # Auto-create as public if it doesn't exist
        workspace = {
            "workspace_id": workspace_id,
            "name": workspace_id,
            "type": "public",
            "passcode": "",
            "created_at": time.time()
        }
        await db.workspaces.insert_one(workspace)
        return workspace

    if workspace.get("type") == "private":
        expected_passcode = workspace.get("passcode")
        if not passcode or passcode != expected_passcode:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access Denied: Private Workspace requires a valid passcode."
            )
            
    return workspace


@app.get("/health")
async def health():
    return {"status": "ok", "redis": "connected", "mongodb": "connected"}


@app.post("/workspace")
async def create_workspace(payload: dict):
    """Creates a room in MongoDB. Generates passcode for private rooms."""
    db = app.state.db
    workspace_id = payload.get("workspace_id")
    name = payload.get("name") or workspace_id
    room_type = payload.get("type", "public").lower() # "public" or "private"
    
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")

    # Check if already exists
    existing = await db.workspaces.find_one({"workspace_id": workspace_id})
    if existing:
        return existing

    # Generate random passcode for private room
    passcode = ""
    if room_type == "private":
        passcode = "sec-" + secrets.token_hex(6) # e.g. sec-f5b28a9c1e3d
        
    workspace_data = {
        "workspace_id": workspace_id,
        "name": name,
        "type": room_type,
        "passcode": passcode,
        "created_at": time.time()
    }
    
    await db.workspaces.insert_one(workspace_data)
    workspace_data.pop("_id", None)
    return workspace_data


@app.get("/workspace/{workspace_id}/files")
async def list_workspace_files(workspace_id: str, passcode: str = None):
    """Lists workspace files from MongoDB after validating passcode."""
    await verify_workspace_access(workspace_id, passcode)
    db = app.state.db
    
    cursor = db.files.find({"workspace_id": workspace_id})
    files = await cursor.to_list(length=None)
    
    for file in files:
        file.pop("_id", None)
        
    return files


@app.post("/workspace/{workspace_id}/files")
async def create_workspace_file(workspace_id: str, payload: dict, passcode: str = None):
    """Registers a file creation in MongoDB and tracks in Redis server."""
    await verify_workspace_access(workspace_id, passcode)
    db = app.state.db
    room_manager = app.state.room_manager
    
    file_id = payload.get("path") or payload.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="path/file_id is required")

    # Track file in Redis set (backwards compatible)
    await room_manager.redis.sadd(workspace_files_key(workspace_id), file_id)

    file_data = {
        "workspace_id": workspace_id,
        "id": file_id,
        "name": payload.get("name") or file_id.split('/')[-1],
        "path": file_id,
        "content": payload.get("content") or "",
        "language": payload.get("language") or "typescript",
        "updated_at": time.time()
    }
    
    # Save metadata to MongoDB
    await db.files.update_one(
        {"workspace_id": workspace_id, "path": file_id},
        {"$set": file_data},
        upsert=True
    )
    
    file_data.pop("_id", None)
    return file_data


@app.delete("/workspace/{workspace_id}/files/{file_id:path}")
async def delete_workspace_file(workspace_id: str, file_id: str, passcode: str = None):
    """Deletes the file metadata from MongoDB and clears Redis updates."""
    await verify_workspace_access(workspace_id, passcode)
    db = app.state.db
    room_manager = app.state.room_manager
    
    # Delete metadata from MongoDB
    await db.files.delete_one({"workspace_id": workspace_id, "path": file_id})
    
    # Clean cache and file listing in Redis
    await room_manager.remove_file(workspace_id, file_id)
    
    return {"workspace_id": workspace_id, "file_id": file_id, "deleted": True}


@app.websocket("/ws/{workspace_id}/{file_id:path}")
async def websocket_file_endpoint(websocket: WebSocket, workspace_id: str, file_id: str, passcode: str = None):
    """WebSocket endpoint for collaborative file editing synced via Redis cache."""
    # Check MongoDB room privacy passcode
    try:
        await verify_workspace_access(workspace_id, passcode)
    except HTTPException:
        await websocket.close(code=3000)
        return

    await websocket.accept()
    room_manager = websocket.app.state.room_manager
    room_name = f"{workspace_id}:{file_id}"

    try:
        # Register file creation/track
        await room_manager.redis.sadd(workspace_files_key(workspace_id), file_id)
        room = await room_manager.get_room(room_name)
        adapter = FastAPIWebsocketAdapter(websocket, room_name)
        await room.serve(adapter)
    except WebSocketDisconnect:
        logger.info(f"WebSocket file disconnected: {room_name}")
    except Exception as e:
        logger.error(f"WebSocket error on file {room_name}: {str(e)}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/{workspace_id}")
async def websocket_endpoint(websocket: WebSocket, workspace_id: str, passcode: str = None):
    """WebSocket endpoint for collaborative session signaling & syncing."""
    # Check MongoDB room privacy passcode
    try:
        await verify_workspace_access(workspace_id, passcode)
    except HTTPException:
        await websocket.close(code=3000)
        return

    await websocket.accept()
    room_manager = websocket.app.state.room_manager

    try:
        room = await room_manager.get_room(workspace_id)
        adapter = FastAPIWebsocketAdapter(websocket, workspace_id)
        await room.serve(adapter)
    except WebSocketDisconnect:
        logger.info(f"WebSocket session disconnected: {workspace_id}")
    except Exception as e:
        logger.error(f"WebSocket session error {workspace_id}: {str(e)}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass