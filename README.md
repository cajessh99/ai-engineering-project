# AI Engineering Project

A small FastAPI app with a health check and a `/ask` endpoint that answers questions using Claude.

## Setup

Requires Python 3.11+. These commands are for PowerShell on Windows.

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If activation fails with "running scripts is disabled", run
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project folder with your Anthropic API key
   (get one at https://console.anthropic.com):

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

   `.env` is gitignored, so the key never gets committed.

## Run

```powershell
uvicorn main:app --reload
```

The server runs at http://127.0.0.1:8000. Interactive API docs are at http://127.0.0.1:8000/docs.

## Endpoints

| Method | Path      | Returns                                   |
| ------ | --------- | ----------------------------------------- |
| GET    | `/`       | `{"message": "Hello, world!"}`            |
| GET    | `/health` | `{"status": "ok"}`                        |
| POST   | `/ask`    | `{"answer": "..."}` for `{"question": "..."}` |

Example:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/ask -Method Post -ContentType 'application/json' -Body '{"question": "What is FastAPI?"}'
```

Each `/ask` request uses a small amount of paid Anthropic API usage.
