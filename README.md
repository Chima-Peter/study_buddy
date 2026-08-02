# StudyBuddy

FastAPI backend for uploading study documents, ingesting them into a searchable index, and answering questions with RAG (retrieval-augmented generation).

## Features

- **Auth** — register, login, logout with JWT (Redis-backed session invalidation)
- **Documents** — signed upload/download via Supabase Storage, metadata CRUD, async ingest
- **Ingest pipeline** — parse → chunk → embed → index (Chroma + Elasticsearch)
- **Chat / RAG** — hybrid, vector, or BM25 search over user documents; answers via Gemini
- **Realtime** — Redis Streams fan-out: SSE for notifications, WebSocket for chat (replacing HTTP query)
- **Notifications** — ingest status updates with cursor pagination + live SSE stream
- **Resilient queues** — RabbitMQ with TTL retries and a dead-letter queue for failed ingest

## Stack

| Layer | Technology |
| --- | --- |
| API | FastAPI, Uvicorn, dependency-injector |
| DB | Local Supabase Postgres (SQLAlchemy async + Alembic) |
| Cache / tokens | Redis |
| Jobs | RabbitMQ (aio-pika, quorum queues) |
| Storage | Supabase Storage (signed URLs) |
| Embeddings | Sentence Transformers (`all-MiniLM-L6-v2`) |
| Vectors | Chroma (local `vector_store/`) |
| Search | Elasticsearch 8 (hybrid RRF / kNN / BM25) |
| LLM | Google Gemini (`gemini-3.1-flash-lite`) |
| Parsing | LangChain loaders, Unstructured, PyMuPDF |

## Requirements

- Python **≥ 3.14** ([uv](https://docs.astral.sh/uv/) recommended)
- Docker Compose stack (Supabase DB/Storage, Redis, RabbitMQ, Elasticsearch, Unstructured)
- Google API key (Gemini)

System packages used by document parsing (see `Dockerfile`): `libmagic`, Poppler, Tesseract, LibreOffice, Pandoc.

## Quick start

```bash
# Install dependencies
uv sync

# Configure environment (create .env — see Configuration below)
# edit .env with your credentials

# Run migrations
uv run alembic upgrade head

# Start the API (consumers start with the app lifespan)
uv run python main.py
```

App defaults: `http://0.0.0.0:8000`

- Swagger: `/api/docs`
- ReDoc: `/api/redoc`
- Health: `GET /api/health`

## Configuration

Settings are loaded from environment variables / `.env` via `app.config.Settings`:

| Variable | Purpose | Default |
| --- | --- | --- |
| `APP_NAME` | OpenAPI title | `StudyBuddy` |
| `DEBUG` | Uvicorn reload | `false` |
| `HOST` / `PORT` | Bind address | `0.0.0.0` / `8000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `CORS_ORIGINS` | Allowed origins | `["*"]` |
| `DATABASE_URL` | Async Supabase Postgres (`postgresql+asyncpg://…`) | local Supabase `postgres` |
| `SYNC_DATABASE_URL` | Sync Supabase Postgres for Alembic (`postgresql+psycopg2://…`) | local Supabase `postgres` |
| `CHECKPOINT_DATABASE_URL` | LangGraph checkpoints (same Supabase DB) | local Supabase `postgres` |
| `REDIS_URL` | Redis | `redis://localhost:6379/0` |
| `RABBITMQ_URL` | AMQP broker | `amqp://guest:guest@localhost:5672/` |
| `JWT_SECRET` / `JWT_ALGORITHM` / `JWT_EXPIRE_MINUTES` | Auth tokens | change in production |
| `GOOGLE_API_KEY` | Gemini | — |
| `SUPABASE_URL` / `SUPABASE_KEY` | Local Supabase Kong + service_role key | `http://localhost:54321` |
| `UNSTRUCTURED_API_URL` / `UNSTRUCTURED_API_KEY` | Self-hosted Unstructured API | `http://localhost:8001` |
| `ELASTICSEARCH_URL` | Search cluster | `http://localhost:9200` |
| `RABBITMQ_MAX_RETRIES` | Ingest retry attempts | `3` |
| `RABBITMQ_RETRY_BASE_MS` | Base delay for TTL retry | `5000` |
| `RABBITMQ_RETRY_MAX_MS` | Cap delay for TTL retry | `300000` |

Do not commit real secrets. Keep `.env` local.

## Document ingest flow

1. `POST /api/system/documents/upload` — create document row + signed upload URL  
2. `PUT` file bytes to the signed URL (Supabase)  
3. `POST /api/system/documents/{id}/ingest` — enqueue on `document_queue` (`202`)  
4. Worker downloads the file, parses/chunks, embeds, writes Chroma + Elasticsearch  
5. Status moves: `pending` → `processing` → `completed` | `failed` | `cancelled`  
6. Failed jobs retry via TTL delay queues; exhausted retries land on `document_queue_dlq`

Retry a failed document with `POST /api/system/documents/{id}/ingest/retry`.

**Allowed extensions:** `.pdf`, `.txt`, `.csv`, `.json`, `.md`, `.markdown`, `.doc`, `.docx`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`

## Realtime (SSE + WebSocket)

Both live channels read from the same per-user **Redis Stream**. Producers (e.g. ingest workers) call `publish_to_user`; clients consume via SSE or WebSocket.

```
Ingest worker / services
        │  publish_to_user(user_id, EventPayload)
        ▼
  Redis Stream (per user)  ←── orchestrate_stream() on connect
        │
        ├── GET  /api/system/notifications/stream   (SSE, one-way)
        └── WS   /api/system/chat                   (bidirectional; chat + events)
```

| Concern | SSE (`/notifications/stream`) | WebSocket (`/chat`) |
| --- | --- | --- |
| Direction | Server → client | Bidirectional |
| Auth | `Authorization: Bearer <token>` | Query `?token=<jwt>` |
| Resume | `Last-Event-ID` header | Query `?cursor=<stream-id>` (default `0`) |
| Use case | Live notification / status push | Chat queries + same event stream |
| Limits | — | Max **5** concurrent connections per user; payload ≤ **64 KB** |

On connect, the server attaches (or creates) the user’s stream. Events are `XREAD`’d, forwarded to the client, then deleted from the stream. After disconnect, the connection key and stream get a short TTL so a quick reconnect can resume.

**Typical event shape** (both channels):

```json
{ "type": "document.status", "data": { "document_id": "...", "name": "...", "status": "completed", "comment": "..." } }
```

Ingest publishes `document.status` as the document moves through `pending` → `processing` → `completed` | `failed` | `cancelled`.

### SSE — notifications

`GET /api/system/notifications/stream` (`text/event-stream`)

- Frames use standard SSE fields: `id`, `event`, `data`
- Idle reads emit `event: ping` keepalives
- Reconnect with `Last-Event-ID` set to the last received message id

### WebSocket — chat (replaces HTTP query)

`WS /api/system/chat?token=<jwt>&cursor=<optional>`

WebSocket is the intended path for RAG chat; `POST /query` remains for now but will be removed once clients migrate.

**Client → server** (JSON object with `type`, or plain `ping`):

| `type` | Purpose |
| --- | --- |
| `ping` | Heartbeat; server replies `pong` (also accepts the bare string `ping`) |
| `query` | RAG question (payload in `data`) — replaces `POST /query` |
| `subscribe` / `unsubscribe` | Channel subscription control |

**Server → client:**

- Greeting: `Hello!`
- Stream events: `{"type": "<event>", "data": {…}}`
- Errors may include the current `cursor` so the client can reconnect and resume

## API overview

All system routes (except health) require `Authorization: Bearer <token>`, unless noted (WebSocket uses `?token=`).

### Auth — `/api/authentication`

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/register` | Create account |
| `POST` | `/login` | Get JWT |
| `POST` | `/logout` | Invalidate token |

### Documents — `/api/system/documents`

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/upload` | Signed upload URL + document record |
| `GET` | `/download?document_id=` | Signed download URL |
| `POST` | `/{id}/ingest` | Start ingest |
| `POST` | `/{id}/ingest/retry` | Retry failed ingest |
| `GET` | `/` | List (cursor pagination, filters) |
| `GET` | `/{id}` | Get one |
| `PUT` / `PATCH` | `/{id}` | Update metadata |
| `DELETE` | `/{id}` | Delete document + related data |

### Chat — `/api/system/chat`

| Method | Path | Description |
| --- | --- | --- |
| `WS` | `/` | Bidirectional chat + Redis stream events (`?token=` required). **Preferred; replaces HTTP query** |
| `POST` | `/query` | RAG Q&A (legacy HTTP; top 5 chunks) — migrate to WebSocket `type: "query"` |

### Notifications — `/api/system/notifications`

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | List (cursor pagination, optional `unread_only`) |
| `PATCH` | `/{id}/read` | Mark as read |
| `GET` | `/stream` | SSE live stream (`Last-Event-ID` to resume) |

## Project layout

```
app/
  authentication/   # users, JWT auth
  system/           # documents, chat, notifications
  core/             # RabbitMQ, ingest, ES, embeddings, handlers
  config.py         # Settings
  container.py      # DI wiring + resource lifecycle
  main.py           # FastAPI app factory
migrations/         # Alembic revisions
scripts/            # load_test_ingest.py + fixtures
vector_store/       # local Chroma persistence
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

## Docker notes

The included `Dockerfile` installs OS deps and Unstructured for document parsing. It targets a Python slim image; wire it to your compose/runtime as needed for Postgres, Redis, RabbitMQ, and Elasticsearch.
