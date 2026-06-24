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
