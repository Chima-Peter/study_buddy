# StudyBuddy

FastAPI backend for uploading study materials, ingesting them into a searchable index, tutoring via RAG chat, and generating chapter study cards with quizzes.

For a client-oriented API walkthrough, see [`docs/student-platform-guide.md`](docs/student-platform-guide.md). OpenAPI at `/api/docs` is the contract source of truth.

## Features

- **Auth** — register, login, logout, short grace-period token refresh; JWT with Redis blacklist
- **Users** — get / update / delete own profile
- **Documents** — signed upload/download via Supabase Storage, metadata CRUD, async ingest
- **Ingest pipeline** — parse → chunk → embed → index (Elasticsearch hybrid search)
- **Chat / RAG** — LangGraph agent over WebSocket; grounded answers via Gemini + document/memory retrieval
- **Conversations** — list, history, and title update (create via WebSocket)
- **Study cards** — async chapter notes + MCQ quizzes per document (RabbitMQ + LangGraph)
- **Notifications** — cursor-paginated inbox + live SSE (`document.status`, study-card events)
- **Resilient queues** — RabbitMQ with TTL retries and DLQs for ingest, study cards, and memory extract

## Stack

| Layer | Technology |
| --- | --- |
| API | FastAPI, Uvicorn, dependency-injector |
| DB | Local Supabase Postgres (SQLAlchemy async + Alembic) |
| Cache / tokens / SSE | Redis |
| Jobs | RabbitMQ (aio-pika, quorum queues) |
| Storage | Supabase Storage (signed URLs) |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`) |
| Search | Elasticsearch 8 (hybrid RRF / kNN / BM25) |
| Agents | LangGraph (chat, study cards) + Postgres checkpoints |
| LLM | Google Gemini (`gemini-3.1-flash-lite`) |
| Parsing | LangChain loaders, Unstructured, PyMuPDF |

## Requirements

- Python **≥ 3.14** ([uv](https://docs.astral.sh/uv/) recommended)
- Docker Engine + Compose v2
- ~8GB free RAM for the compose stack (Elasticsearch + Unstructured)
- Google API key (Gemini)

System packages used by document parsing (see `Dockerfile`): `libmagic`, Poppler, Tesseract, LibreOffice, Pandoc.

## Local infrastructure (Docker Compose)

`docker-compose.yml` runs Supabase (Postgres + Storage via Kong), Redis, RabbitMQ, Elasticsearch, and Unstructured. Host ports are offset from the usual defaults so they do not clash with services already on the machine.

| Service | Host port | Notes |
| --- | --- | --- |
| Postgres (Supabase) | `54322` | Avoids host Postgres on `5432` |
| Kong (Supabase API/Storage) | `54323` | App `SUPABASE_URL` |
| Studio | `54324` | UI at `http://localhost:54324` |
| Redis | `16379` | |
| RabbitMQ AMQP | `25672` | Management UI: `25673` |
| Elasticsearch | `19200` | |
| Unstructured API | `18001` | |

### Prerequisites

- Free host ports listed above
- A repo-root `.env` — start from `.env.docker.example` and fill in `JWT_SECRET` / `GOOGLE_API_KEY`

### Start / stop

```bash
# Configure (first time)
cp .env.docker.example .env
# edit .env — set JWT_SECRET and GOOGLE_API_KEY

docker compose up -d          # background
# docker compose up           # foreground with logs

docker compose ps
docker compose down           # stop, keep volumes
docker compose down -v        # stop and wipe volumes (fresh DB/storage)
```

On first boot, `supabase-init` creates the `documents` storage bucket.

### Verify

```bash
PGPASSWORD=postgres psql -h 127.0.0.1 -p 54322 -U postgres -c 'select 1'

set -a && source .env && set +a
curl -s http://localhost:54323/storage/v1/bucket \
  -H "apikey: $SUPABASE_KEY" \
  -H "Authorization: Bearer $SUPABASE_KEY"
```

Local Supabase uses the standard demo `service_role` JWT (see `.env.docker.example`). It is for local development only.

## Quick start

```bash
# 1. Start infra (see Local infrastructure above)
docker compose up -d

# 2. Install app dependencies
uv sync

# 3. Ensure .env matches compose ports (see .env.docker.example)

# 4. Run migrations
uv run alembic upgrade head

# 5. Start the API (consumers start with the app lifespan)
uv run python main.py
```

App defaults: `http://0.0.0.0:8000`

- Swagger: `/api/docs`
- ReDoc: `/api/redoc`
- Health: `GET /api/health`

## Configuration

Settings are loaded from environment variables / `.env` via `app.config.Settings`. Defaults match the compose host ports:

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_NAME` | OpenAPI title | `StudyBuddy` |
| `DEBUG` | Uvicorn reload | `false` |
| `HOST` / `PORT` | Bind address | `0.0.0.0` / `8000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `CORS_ORIGINS` | Allowed origins | `["*"]` |
| `DATABASE_URL` | Async Supabase Postgres (`postgresql+asyncpg://…`) | `…@localhost:54322/postgres` |
| `SYNC_DATABASE_URL` | Sync Supabase Postgres for Alembic (`postgresql+psycopg2://…`) | `…@localhost:54322/postgres` |
| `CHECKPOINT_DATABASE_URL` | LangGraph checkpoints (same Supabase DB) | `…@localhost:54322/postgres` |
| `REDIS_URL` | Redis | `redis://localhost:16379/0` |
| `RABBITMQ_URL` | AMQP broker | `amqp://guest:guest@localhost:25672/` |
| `JWT_SECRET` / `JWT_ALGORITHM` / `JWT_EXPIRE_MINUTES` | Auth tokens | change in production |
| `JWT_REFRESH_GRACE_MINUTES` | Post-expiry refresh window | `10` |
| `GOOGLE_API_KEY` | Gemini | — |
| `CHAT_MODEL_NAME` / `SUMMARIZER_MODEL_NAME` / `QUERY_MODEL_NAME` | Gemini model ids | `gemini-3.1-flash-lite` |
| `SUPABASE_URL` / `SUPABASE_KEY` | Local Kong + service_role key | `http://localhost:54323` |
| `UNSTRUCTURED_API_URL` / `UNSTRUCTURED_API_KEY` | Self-hosted Unstructured API | `http://localhost:18001` |
| `ELASTICSEARCH_URL` | Search cluster | `http://localhost:19200` |
| `RABBITMQ_MAX_RETRIES` | Ingest retry attempts | `3` |
| `RABBITMQ_RETRY_BASE_MS` | Base delay for TTL retry | `5000` |
| `RABBITMQ_RETRY_MAX_MS` | Cap delay for TTL retry | `300000` |

Do not commit real secrets. Keep `.env` local.

## Document ingest flow

1. `POST /api/documents/upload` — create document row + signed upload URL  
2. `PUT` file bytes to the signed URL (Supabase)  
3. `POST /api/documents/{id}/ingest` — enqueue on `document_queue` (`202`)  
4. Worker downloads the file, parses/chunks, embeds, indexes into Elasticsearch  
5. Status moves: `pending` → `processing` → `completed` | `failed` | `cancelled`  
6. Failed jobs retry via TTL delay queues; exhausted retries land on `document_queue_dlq`

Retry a failed document with `POST /api/documents/{id}/ingest/retry`.

**Allowed extensions:** `.pdf`, `.docx`, `.txt`, `.md`, `.markdown`, `.doc`, `.rtf`, `.odt`, `.epub`  
Uploads go directly to Supabase via signed URL (not through the API), so the API does not enforce a file size limit.

## Realtime

### SSE — notifications

`GET /api/notifications/stream` (`text/event-stream`)

Producers (ingest / study-card workers) publish to a per-user Redis Stream. Clients consume via SSE.

- Auth: `Authorization: Bearer <token>`
- Frames use standard SSE fields: `id`, `event`, `data`
- Resume with `Last-Event-ID`
- Idle reads emit `event: ping` keepalives

**Typical payload:**

```json
{ "type": "document.status", "data": { "document_id": "...", "name": "...", "status": "completed", "comment": "..." } }
```

Also emitted: `study_cards_generated`, `study_cards_failed`.

### WebSocket — tutor chat

`WS /api/chat?token=<jwt>`

- Max **5** concurrent connections per user; query payload ≤ **64 KB**
- Auth via query `?token=` (not a header)
- Server greets with a heartbeat `Ping`

**Client → server** (flat JSON — not a `type`/`data` envelope):

```json
{
  "query": "Explain mitosis",
  "conversation_id": "<uuid optional>",
  "document_ids": ["<uuid optional>"]
}
```

| Field | Behavior |
| --- | --- |
| Omit `conversation_id` | Creates a new conversation |
| `document_ids` | Scope RAG to those documents |
| Legacy `document_id` | Accepted; coerced to a one-element list |
| `query: "ping"` | Heartbeat `Pong` |

**Server → client** (`type` field):

| `type` | Meaning |
| --- | --- |
| `heartbeat` | Ping / Pong keep-alive |
| `chat.response` | Answer chunk (`response`) |
| `chat.title` | Auto-generated title (first turn) |
| `chat.done` | Turn finished |
| `chat.error` / `error` | Failure (`message`) |

## API overview

Paths live under `/api/...` — there is **no** `/api/system` prefix. Most HTTP routes require `Authorization: Bearer <token>` (WebSocket uses `?token=`).

### Auth — `/api/authentication`

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/register` | Create account + JWT |
| `POST` | `/login` | Get JWT |
| `POST` | `/refresh` | Exchange recently expired JWT (grace window) |
| `POST` | `/logout` | Blacklist current token |

### Users — `/api/users`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/me` | Current profile |
| `PATCH` | `/me` | Update profile (≥1 field) |
| `DELETE` | `/me` | Delete account |

### Documents — `/api/documents`

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/upload` | Signed upload URL + document record |
| `GET` | `/download?document_id=` | Signed download URL |
| `POST` | `/{id}/ingest` | Start ingest (`202`) |
| `POST` | `/{id}/ingest/retry` | Retry failed ingest |
| `GET` | `/` | List (cursor pagination, filters) |
| `GET` | `/{id}` | Get one |
| `PATCH` | `/{id}` | Update metadata |
| `DELETE` | `/{id}` | Delete document + related data |

### Chat — `/api/chat`

| Method | Path | Description |
| --- | --- | --- |
| `WS` | `/?token=` | Streaming tutor chat |

### Conversations — `/api/conversations`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | List (cursor pagination) |
| `GET` | `/{id}` | History + messages |
| `PATCH` | `/{id}` | Update title |

### Study cards — `/api/study-cards`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | List decks (cursor pagination, optional status) |
| `POST` | `/{document_id}` | Queue generation (`202`; `409` if success/in progress) |
| `GET` | `/{document_id}` | Get status + result (chapters, quizzes) |

### Notifications — `/api/notifications`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | List (cursor pagination, optional `unread_only`) |
| `PATCH` | `/read` | Bulk mark read |
| `PATCH` | `/{id}/read` | Mark one as read |
| `GET` | `/stream` | SSE live stream (`Last-Event-ID` to resume) |

## Project layout

```
app/
  authentication/   # users, JWT auth
  system/           # documents, chat, conversations, study cards, notifications
  agent/            # LangGraph chat + study-cards agents
  handlers/         # RabbitMQ consumers (ingest, study cards, memory, mail)
  rag/              # ingest pipeline, parsers, chapter split
  memory/           # internal memory extract/store (Elasticsearch)
  core/             # Redis, RabbitMQ, ES, embeddings, middleware
  config.py         # Settings
  container.py      # DI wiring + resource lifecycle
  main.py           # FastAPI app factory
docs/               # client platform guide
migrations/         # Alembic revisions
scripts/            # load_test_ingest.py + helpers
main.py             # uvicorn entrypoint
```

## Migrations

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
```

## Load testing ingest

```bash
# Generate fixtures only
uv run python scripts/load_test_ingest.py --generate-only --profile full

# Upload + ingest against a running API
uv run python scripts/load_test_ingest.py \
  --email you@example.com --password 'YourPassword' --profile quick
```

Default base URL in the script is `http://127.0.0.1:8080/api` — override if your `PORT` differs.

## App Docker image

The included `Dockerfile` builds the API image (OS deps + parsing tools). Local dependencies come from `docker-compose.yml` (see **Local infrastructure** above); the API itself is usually run with `uv` / `main.py` during development.
