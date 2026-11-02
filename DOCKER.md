# Local Docker stack: implementation and verification guide

This documents a locally tested Docker stack, **not a verified production deployment**. Retrieval algorithms, candidate limits, RRF constant, model identifiers, prompts, answer defaults and frozen evaluation artifacts are unchanged. Server-mode Qdrant can differ from embedded brute-force search through ANN implementation, float32 normalization or tie ordering; live parity must be measured, not assumed.

## Inspected application

| Area | Actual implementation |
|---|---|
| API | `app.py`, FastAPI object `app`, lifecycle initializes one `RAGEngine`; local command `python -m uvicorn app:app --host 127.0.0.1 --port 8000` |
| UI | `frontend.py`; local command `python -m streamlit run frontend.py --server.port 8501`; HTTP backend selected through `API_BASE_URL` |
| Existing database | Embedded `QdrantClient(path=...)`, `qdrant_storage/`; **not** a Qdrant server database |
| Container database | `QdrantClient(url=...)` when `QDRANT_URL` is set; collection remains `supreme_court_2023`, 384-dimensional cosine vectors |
| Models | Eager FastEmbed initialization: `BAAI/bge-small-en-v1.5` and `Xenova/ms-marco-MiniLM-L-6-v2`; CPU image; first startup may download weights |
| Sparse retrieval | Existing `BM25Okapi` built in API memory from `data/chunks.jsonl`; not moved into Qdrant |
| Generation | Existing Google GenAI SDK and `GEMINI_API_KEY`; default `gemini-2.5-flash`, V1, `hybrid_reranked`, five sources; unchanged |

The Docker API command binds `0.0.0.0` **inside** the container with one worker. Compose publishes API/UI only on host loopback. Qdrant has **no published ports** and belongs only to an internal Docker network. The API also has an egress-capable application network for model downloads and Gemini. This is a local stack, not an authenticated public service.

## Configuration and secrets

| Setting | Local Python | Compose |
|---|---|---|
| `GEMINI_API_KEY` | Existing environment / private `.env` loader | Runtime API environment only; optional for retrieval, required for generation |
| `QDRANT_URL` | Unset/blank preserves embedded storage | Fixed to `http://qdrant:6333` for API; migration URL passed explicitly |
| `QDRANT_API_KEY` | Optional server authentication; ignored in embedded mode | **Required nonempty** shared server/API/migration key; Compose refuses an empty/missing value |
| `API_BASE_URL` | Defaults to `http://127.0.0.1:8000` | `http://api:8000` in Streamlit |
| `FASTEMBED_CACHE_PATH` | Existing FastEmbed behavior | `/models/fastembed` in named model volume |
| `HF_HOME` | Existing library behavior | `/models/huggingface` in named model volume |

`.env.example` contains no secrets. If `.env` already exists, **do not overwrite it**. Otherwise copy the template to `.env`, then privately add a Gemini key (for generation) and a randomly generated Qdrant key. Use a password manager or a cryptographically secure generator for the Qdrant key; it is an application secret, not a Google credential. Never reuse a provider key as the Qdrant key. Compose reads `.env` for interpolation; it is never copied or mounted into an image/container. Only the API receives the Gemini credential. Existing local `.env` loading behavior is unchanged. Environment credentials remain visible to operators with Docker access; do not share `docker inspect` or expanded `docker compose config` output. Use `docker compose config --quiet` for validation without printing credentials.

Keep `.env` untracked (existing `.gitignore`). Do not add secrets as Docker build arguments or commit the migration export. `requirements-docker.txt` pins direct runtime packages to the inspected local versions, including numerical libraries; transitive dependencies are not fully locked. The Qdrant server tag is explicitly `v1.17.0`. The running server version and 21,451-point collection were verified during the client-alignment check below. The server key is deliberately required: an explicitly empty Qdrant API-key setting can enable authentication with an unusable empty credential, so blank-key mode is not used. The Docker client is pinned to `1.17.1`, aligned with the server's minor version. Used client APIs were checked against that release, and live retrieval and generation checks passed. The local Python requirements remain unpinned; container checks do not guarantee compatibility of arbitrary future local installs.

## Persistence and image boundaries

| Artifact | Source / persistence |
|---|---|
| Original judgments and PDFs | `data/judgments.jsonl`, `data/pdfs/`; untouched, not needed by live application and not mounted |
| Chunk corpus | `data/chunks.jsonl`; read-only bind mount for API and migration; **53,354,502 bytes** in inspected repository |
| Existing embedded index | `qdrant_storage/`; never mounted into Qdrant server; unchanged |
| Export of existing vectors/payloads | New `data/qdrant_server_export.jsonl`; read-only migration bind mount; ignored by Git and Docker build context |
| Server database | Named volume `supreme-court-rag_qdrant_data` mounted at `/qdrant/storage` |
| Server snapshots | Named volume `supreme-court-rag_qdrant_snapshots` mounted at `/qdrant/snapshots` |
| Downloaded models | Named volume `supreme-court-rag_model_cache` mounted at `/models` in API |
| UI metrics | Existing `data/full_benchmark_metrics_v2.json`; read-only API mount; remains the **development** benchmark |

Volume names above assume the supplied Compose project name, without `-p` overrides. `.dockerignore` uses an allowlist; neither `.env`, `.venv`, PDFs, data, reports, evaluation workbooks, local Qdrant storage nor model caches enter the build context. Dockerfile also uses explicit `COPY` instructions. Only code and Docker runtime dependencies enter the application image. The same image serves API, UI and the one-shot migration; UI does not initialize models or access the corpus/database.

Bind mounts use `create_host_path: false` so missing artifacts fail instead of silently becoming directories. Application processes use non-root UID 10001; source files must be readable by that user. Named model-volume initialization copies image directory ownership; custom/pre-existing volumes may require an operator permission fix. Do not delete them as a workaround.

## Safe first migration and startup

Prerequisites: Docker Desktop with Linux containers and working Compose v2, sufficient disk for a temporary database copy/export/images/volumes, internet for images/packages/model downloads, and the existing prepared corpus/index. No re-embedding, corpus rebuild, paid generation or evaluation rerun is part of migration.

### 1. Optional pre-migration retrieval baseline

While the **existing local API** is running, capture a new operational smoke baseline:

```powershell
python -B docker/smoke_test.py --skip-streamlit --write-baseline data/docker_local_retrieval_baseline.json
```

This queries four retrieval modes for one non-benchmark legal question, preserving exact ordered IDs, excerpts and source metadata for a later comparison. It does not generate answers or overwrite a frozen evaluation artifact. The command refuses to overwrite an existing baseline; choose a new filename for another run. It is not a replacement for a broad parity study.

### 2. Stop embedded database users; export without writing the original

Stop the local Uvicorn backend and all other embedded Qdrant users. Do not run `embed_store.py`: its existing incomplete-collection path deletes/rebuilds collections. This migration never invokes it.

```powershell
python -B migrate_qdrant.py export --local-backend-stopped
```

**Current repository status:** this export has already completed successfully for all 21,451 points. `data/qdrant_server_export.jsonl` is **227,685,783 bytes**, with SHA-256 `37da760607dcbf2e0e216ed6ccfa8870526c09c608852dee6cac61451a49956a`. Reuse it for the first Docker import; do not rerun export to the same path (the tool correctly refuses overwrites). These are local operational migration artifacts, not evaluation results.

Export:

1. Validates **21,451** unique chunk records and their deterministic UUIDs.
2. Acquires the existing source lock without creating/truncating it; refuses active local users and source links/junctions.
3. Hashes source files, copies storage into an OS temporary directory, and opens **only the copy** with `QdrantClient`.
4. Verifies the source collection, all IDs, 384-dimensional finite vectors and **every payload field**, including full text and citation metadata, against chunks.
5. Rechecks original hashes after releasing the lock; publishes a new export without overwriting any existing file.

Keep local users stopped until export completes. Hashes detect changes but cannot undo an external process's writes. The export requires additional local disk space and contains full judgment excerpts; protect its permissions. Do not modify or delete the embedded source.

### 3. Build and start

From the repository root, after privately configuring `.env`:

```powershell
docker version
docker compose version
docker compose config --quiet
docker compose build
docker compose up -d --wait --wait-timeout 1800
docker compose ps -a
docker compose logs --tail 100 qdrant migrate api streamlit
```

Normal startup order:

1. Qdrant `/readyz` becomes healthy.
2. One-shot `migrate` imports existing vectors (no embedding calls). It creates a collection **only if absent**, checks all pre-existing points before any write, adds only missing matching IDs, and never deletes or repairs divergent records.
3. Migration verifies **exactly 21,451 IDs**, exact canonical payload equality and bounded vector roundoff. Per-coordinate `rel_tol=1e-6`, `abs_tol=1e-7` **and** whole-vector L2 difference ≤ `1e-6` accommodate server float32 cosine normalization; material drift fails verification. This is not bit-exact vector equivalence.
4. API starts after migration exits successfully; it builds BM25 and loads unchanged models. Health checks require API engine readiness and the expected server point count.
5. Streamlit starts after API health passes; its health probe calls `/_stcore/health`.

The export must remain available for future migration/verification runs. First startup can be slow due to package/model downloads; the health grace period is not measured startup performance. The import requires exclusive destination writers: keep API/external writers stopped. A failed import leaves partial data for investigation/resume rather than deleting a volume. If a collection has unexpected IDs/payloads/vectors or schema, stop and investigate—do not bypass checks or rebuild over it.

Open:

- API docs: `http://127.0.0.1:8000/docs`
- Streamlit: `http://127.0.0.1:8501`

## Acceptance tests after Docker becomes available

### Endpoints, retrieval parity and actual answer generation

```powershell
python -B docker/smoke_test.py --compare-baseline data/docker_local_retrieval_baseline.json
```

If no local baseline was captured, run `python -B docker/smoke_test.py` for health and four-mode checks, but do not claim local/server parity. It tests dense, BM25, Hybrid RRF and reranked retrieval, five unique judgments per mode, and citation/excerpt presence. Score values are intentionally excluded from exact baseline equality because implementations can have numerical differences. Any rank/excerpt difference fails and must be investigated without tuning the frozen benchmark.

One **real paid/quota-consuming** Gemini request, explicitly opt-in:

```powershell
python -B docker/smoke_test.py --generate
```

The server obtains its key at runtime, not from this script or image. A passing response check means nonempty answer and citations—not legal correctness or semantic entailment. Missing credentials, quota errors and model availability must be reported as failures/blockers, not mocked successes.

**Manual UI acceptance:** open Streamlit, enter “What principles govern anticipatory bail under Section 438 CrPC?”, choose each retrieval mode and click **Inspect retrieved passages**. Then click **Generate grounded answer** once with the intended setting; confirm an actual answer and sources render, and inspect API logs for errors. This is a separate real-browser interaction; an HTTP health probe does not establish it. Each generation uses provider quota.

### Collection verification, restart and persistence

With the API stopped (UI may remain running but requests will fail), verify all source payloads/vectors through the one-shot service:

```powershell
docker compose stop api
docker compose run --rm migrate python migrate_qdrant.py verify --url http://qdrant:6333 --file /migration/points.jsonl --chunks /app/data/chunks.jsonl --destination-writes-stopped
docker compose up -d --wait --wait-timeout 1800
```

Capture a **new** post-migration operational baseline if not comparing to a local baseline:

```powershell
python -B docker/smoke_test.py --write-baseline data/docker_server_retrieval_baseline.json
docker compose restart qdrant api streamlit
docker compose up -d --wait --wait-timeout 1800
python -B docker/smoke_test.py --compare-baseline data/docker_server_retrieval_baseline.json
docker compose stop api
docker compose run --rm migrate python migrate_qdrant.py verify --url http://qdrant:6333 --file /migration/points.jsonl --chunks /app/data/chunks.jsonl --destination-writes-stopped
docker compose up -d --wait --wait-timeout 1800
```

The repeat full verification is the point-count/payload persistence check; a retrieval response alone is insufficient. Dependency conditions govern Compose startup, not automatic cascading runtime restarts. A transient dependency failure can make the API unhealthy; inspect logs rather than assuming Compose heals all failures.

### Measure actual resources and server disk

After the stack is healthy and again after a query:

```powershell
docker stats --no-stream
docker compose exec qdrant du -sk /qdrant/storage /qdrant/snapshots
docker system df -v
```

Record actual CPU, memory, process count, image/volume usage, and KiB from `du`; do not treat Docker Desktop's overall VM usage or `docker system df` shared-layer size as per-service resident memory. Capture observed startup/query timings separately if needed. No measured Docker resource claim exists until these commands run successfully.

## Start/stop without losing data

After first export/build:

```powershell
docker compose up -d --wait --wait-timeout 1800
```

Stop processes but retain containers, images and volumes:

```powershell
docker compose stop
```

Or remove this stack's containers and networks **while retaining named volumes**:

```powershell
docker compose down
```

**Never use volume-removal flags, `docker volume rm`, volume pruning, or delete `qdrant_storage/`.** Backup persistent volumes before Docker Desktop resets or upgrades. Do not change the Compose project name casually: a different name selects different volumes, appearing to lose the old collection even though it still exists.

## Local development remains available

Unset `QDRANT_URL` (and do not set it to the Compose-only hostname in local `.env`). Run the existing local API/UI commands from the repository root. They continue using the original embedded index. Do not start multiple embedded clients simultaneously against that same directory. Local and server indexes are independent copies; this phase does not implement ongoing synchronization or automatic corpus ingestion.

## Initial packaging verification (historical)

- `docker version`, `docker compose version`, `docker compose build` and `docker compose config --quiet` were attempted: **`docker: command not found`**. Standard Windows Docker Desktop paths were also absent. No Docker daemon or browser stack was available.
- **116 offline tests passed**, including migration safety/refusal/resume tests, connection-selection tests and Compose structural checks. Python sources compiled in memory; YAML parsing is not equivalent to validation by Docker Compose.
- Original embedded SQLite was inspected read-only with `mode=ro&immutable=1`: **21,451 points**. Original storage files total **174,858,844 bytes** (~166.76 MiB); this is **not Qdrant server volume size**.
- The source-side export completed: **21,451** unique IDs, all payload metadata and vectors validated against the chunks; original source-file hashes were unchanged. The export contains existing vectors and did not load embedding/reranking models. Original corpus, PDF, evaluation and historical-report hashes also matched the earlier 888-file preservation inventory.
- No server import, container health/log check, live retrieval parity, browser query, Gemini generation, restart persistence, container resource measurement or server disk measurement has been completed. No paid API call was made. The host process had no `GEMINI_API_KEY` environment variable; the private `.env` was not inspected, so credential availability is not inferred from that alone.

Those were the initial packaging constraints. Subsequent runtime checks supersede the applicable blockers as recorded below; the historical observations are retained rather than silently rewritten.

## Subsequent runtime verification: client/server alignment

- Docker Desktop became available, and the running server reported **1.17.0** with an exact count of **21,451** points.
- `requirements-docker.txt` pins **qdrant-client 1.17.1**. All used methods, keyword arguments and model fields were checked against this release; no retrieval/generation implementation change was needed. Its dependency resolver selected `portalocker 3.2.0`; embedding, numerical, reranking, BM25 and generation package versions remained unchanged.
- **116 existing tests passed against client 1.17.1** in an isolated temporary package environment, and **33 Python sources compiled** in memory. The later Git-publication seed-privacy test brings the local suite to **117 passing tests**; it changes only review preparation, not application behavior.
- `docker compose build api` rebuilt the shared application image successfully. `docker compose up -d --no-deps --no-build --force-recreate --wait --wait-timeout 900 api streamlit` recreated only API/UI; both became healthy. `pip check` found no broken image dependencies.
- API and UI images both reported client **1.17.1**. The mismatch warning was absent from current startup logs.
- All four retrieval modes passed the legal smoke query. Complete responses matched the pre-update baseline exactly, including ranks, scores, citations and excerpts. This is one-query regression evidence, not proof of universal parity.
- One real `/api/query` request using the unchanged `gemini-2.5-flash` default returned HTTP 200, a nonempty answer and citations, consuming provider quota. This verifies generation transport/output, not legal correctness.
- Qdrant and migration container IDs remained unchanged; Qdrant's start timestamp and named-volume mounts were unchanged. **No import was rerun.** A SHA-256 fingerprint across all stored IDs, payloads and vectors matched before/after the update, with **21,451** exact points.
- Browser-level interaction, an explicit Qdrant-restart persistence test, container resource usage and server-volume disk measurements were not independently rerun during client alignment. Use the acceptance commands above for those checks.

A source-only checkout intentionally omits the corpus, local database, export, credentials and private review artifacts. First-time users need prepared artifacts and the initial migration procedure; operators of the already populated stack should not rerun import just to update application dependencies.
