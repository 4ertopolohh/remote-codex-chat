# Local chat

Start the backend from `backend/` with `./.venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000`.
Start the frontend from `frontend/` with `npm run dev`. Open the Vite URL shown in the terminal. Vite proxies `/ws/chat` to the backend.

The backend selects one local project. By default it uses this repository's root. Set `RC_PROJECT_PATH` in the backend environment to use another existing project directory. The browser never sends a filesystem path.

The client sends `{"type":"submit_prompt","text":"..."}`. The server sends `ready`, `turn_started`, `assistant_delta` (with `text`), `agent_status` (with `status`), `turn_completed` (with `status`), or `error` (with `code`). One browser connection and one turn at a time are supported. Closing the connection interrupts a running turn.
