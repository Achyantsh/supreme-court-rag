# Run the local Supreme Court RAG demo

Run these commands from the repository root. Do not copy or
replace the existing corpus, Qdrant storage, evaluation artifacts, or
`rag_engine.py`/`query_pipeline.py`.

Open PowerShell in the repository root and activate the existing virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If the environment is already provisioned, the install is optional. Start the
backend from the repository root:

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Wait for `RAG engine initialized`. On first run, model loading can take time.
Do not start a second backend against the same `qdrant_storage` directory:
local Qdrant permits one process at a time.

Open a second PowerShell terminal in the same repository root and run:

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run frontend.py --server.port 8501
```

Open `http://localhost:8501`. The API docs are at `http://127.0.0.1:8000/docs`.

The backend reads existing project files and starts the model/index once at startup. Run both commands with the repository root as the current directory because the existing RAG modules use relative paths for local data and `.env`.

Smoke-test the backend from a third PowerShell window:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8000/api/metrics
$body = @{ question = "What principles govern anticipatory bail under Section 438 CrPC?"; retrieval_mode = "hybrid_rrf"; top_k = 3 } | ConvertTo-Json
Invoke-WebRequest http://127.0.0.1:8000/api/retrieve -Method Post -ContentType "application/json" -Body $body
```

Do not share `.env`, your Gemini API key, or other secrets. This phase is
local-only and does not configure Docker or AWS. Docker is optional; if it is
not installed, run the two local processes above.
