# Frontend Connection Setup

This document explains how to connect a React + Yjs frontend to the `backend-ccsl-2026` FastAPI backend.

## Backend WebSocket endpoint

The backend exposes a Yjs-compatible WebSocket at:

- `ws://localhost:8000/ws/{workspace_id}`

If you expose the app through ngrok, use `wss://` with the ngrok HTTPS address:

- `wss://quench-mortified-amaze.ngrok-free.dev/ws/{workspace_id}`

Replace `{workspace_id}` with your room or document identifier.

Example:

- `wss://quench-mortified-amaze.ngrok-free.dev/ws/my-room`

> Note: `curl` is not a reliable WebSocket client for this test. Use browser JS or `wscat` for websocket checks.

## Recommended frontend stack

Use the following packages:

- `yjs`
- `y-websocket`

Install them with npm:

```bash
npm install yjs y-websocket
```

## React integration example

Create or update `src/App.jsx` with this example:

```jsx
import { useEffect, useRef, useState } from 'react'
import * as Y from 'yjs'
import { WebsocketProvider } from 'y-websocket'

function App() {
  const ydocRef = useRef(null)
  const providerRef = useRef(null)
  const ytextRef = useRef(null)
  const [value, setValue] = useState('')

  useEffect(() => {
    const doc = new Y.Doc()
    ydocRef.current = doc

    const workspaceId = 'my-room'
    const provider = new WebsocketProvider('ws://quench-mortified-amaze.ngrok-free.dev/ws', workspaceId, doc)
    providerRef.current = provider

    const ytext = doc.getText('shared-text')
    ytextRef.current = ytext

    const updateValue = () => {
      setValue(ytext.toString())
    }

    updateValue()
    ytext.observe(updateValue)

    provider.on('status', (event) => {
      console.log('Yjs provider status:', event.status)
    })

    return () => {
      ytext.unobserve(updateValue)
      provider.destroy()
      doc.destroy()
    }
  }, [])

  const handleChange = (event) => {
    const newValue = event.target.value
    setValue(newValue)

    const ytext = ytextRef.current
    if (!ytext) return

    ytext.delete(0, ytext.length)
    ytext.insert(0, newValue)
  }

  return (
    <div style={{ padding: '1rem' }}>
      <h1>Yjs Collaborative Text</h1>
      <textarea
        value={value}
        onChange={handleChange}
        rows={10}
        cols={80}
        placeholder="Type here and share with others"
      />
      <p>Room: <strong>my-room</strong></p>
    </div>
  )
}

export default App
```

## Important notes

- The backend is already configured to accept binary Yjs sync messages.
- Use the same `workspaceId` in the frontend and backend to share document state.
- The frontend provider expects the server path prefix to be passed as the first argument and the room name as the second.

## Minimal frontend checklist

1. Start backend:

   ```bash
   uvicorn app.controller.main:app --host 0.0.0.0 --port 8000
   ```

2. Start frontend (assuming Create React App or similar):

   ```bash
   npm start
   ```

3. Open the app in the browser.

4. Confirm the provider connects to `ws://quench-mortified-amaze.ngrok-free.dev/ws/my-room`.

## Troubleshooting

- If the WebSocket fails to connect, verify the backend is running and accessible on port `8000`.
- If no document updates appear, ensure the room ID matches exactly in both frontend and backend.
- Use browser console logs to inspect provider `status` and connection errors.

## Multi-file workspaces (files, rooms, mapping)

This backend now supports per-file collaborative rooms and a workspace-level room. Two supported patterns:

- Per-file rooms (recommended):
  - WebSocket path: `ws://<host>/ws/{workspace_id}/{file_id}`
  - Redis key: `yjs:{workspace_id}:{file_id}`
  - Example connect URL (local): `ws://localhost:8000/ws/my-workspace/main.py`
  - Example connect URL (ngrok / secure): `wss://<ngrok-host>/ws/my-workspace/main.py`

- Workspace-level single doc (all files inside one Y.Doc):
  - WebSocket path: `ws://<host>/ws/{workspace_id}`
  - Files stored inside the Y.Doc as a `Y.Map` (advanced; not the default)

Choose per-file rooms for simpler per-file persistence and independent editing.

## Backend file management API

The backend exposes simple REST endpoints for workspace file metadata:

- List files in workspace:

```http
GET /workspace/{workspace_id}/files
```

- Create/register a file in a workspace:

```http
POST /workspace/{workspace_id}/files
Content-Type: application/json
{
  "file_id": "main.py"
}
```

- Delete a file (removes Redis store):

```http
DELETE /workspace/{workspace_id}/files/{file_id}
```

## Frontend: per-file React example

Use `yjs` + `y-websocket`. Connect to a specific file by using the workspace+file as the Yjs room name (the backend maps `workspace:file`). Example `src/App.jsx` snippet:

```jsx
import { useEffect, useRef, useState } from 'react'
import * as Y from 'yjs'
import { WebsocketProvider } from 'y-websocket'

function FileEditor({ workspaceId='my-workspace', fileId='main.py' }) {
  const ydocRef = useRef(null)
  const providerRef = useRef(null)
  const ytextRef = useRef(null)
  const [value, setValue] = useState('')

  useEffect(() => {
    const doc = new Y.Doc()
    ydocRef.current = doc

    // provider base url + room name (backend expects workspace:file)
    const roomName = `${workspaceId}:${fileId}`
    const provider = new WebsocketProvider('wss://quench-mortified-amaze.ngrok-free.dev/ws', roomName, doc)
    providerRef.current = provider

    const ytext = doc.getText('shared-text')
    ytextRef.current = ytext

    const updateValue = () => setValue(ytext.toString())
    updateValue()
    ytext.observe(updateValue)

    return () => {
      ytext.unobserve(updateValue)
      provider.destroy()
      doc.destroy()
    }
  }, [workspaceId, fileId])

  const handleChange = (e) => {
    const newValue = e.target.value
    setValue(newValue)
    const ytext = ytextRef.current
    if (!ytext) return
    ytext.delete(0, ytext.length)
    ytext.insert(0, newValue)
  }

  return (
    <textarea value={value} onChange={handleChange} rows={20} cols={80} />
  )
}

export default FileEditor
```

## Redis and environment variables

- Default Redis URL used by backend: `redis://localhost:6379`
- Override with environment variable:

```bash
export REDIS_URL=redis://user:pass@redis-host:6379/0
```

## Quick test commands

- Use `wscat` to open a per-file room:

```bash
npm install -g wscat
wscat -c wss://quench-mortified-amaze.ngrok-free.dev/ws/my-workspace/main.py
```

- Use `curl` for REST file API tests:

```bash
curl -X POST -H "Content-Type: application/json" -d '{"file_id":"main.py"}' http://localhost:8000/workspace/my-workspace/files
curl http://localhost:8000/workspace/my-workspace/files
curl -X DELETE http://localhost:8000/workspace/my-workspace/files/main.py
```

## Notes & troubleshooting

- If using ngrok, prefer `wss://` (ngrok provides HTTPS) and confirm the forwarded target is `http://localhost:8000`.
- If you see connection redirects (HTTP 307), point your client to `wss://<ngrok-host>` rather than `ws://`.
- Confirm Redis is reachable and `REDIS_URL` is set when running the app under different environments (containers, CI).

---

If you'd like, I can also add a tiny example React repo (`create-react-app`) in this workspace demonstrating file open/create/delete flows and connecting to a specific file room.
