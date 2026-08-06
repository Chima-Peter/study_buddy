# StudyBuddy Student Platform Guide

A detailed blueprint for building a rich student web/mobile client on top of every **live** StudyBuddy API.

> **Contract source of truth:** `/api/docs` and `/api/openapi.json`  
> Paths live under `/api/...` — there is **no** `/api/system` prefix (README may be stale).

---

## Table of contents

1. [Overview](#1-overview)
2. [Architecture the client depends on](#2-architecture-the-client-depends-on)
3. [Response conventions](#3-response-conventions)
4. [Authentication & profile](#4-authentication--profile)
5. [Document library](#5-document-library)
6. [Tutor chat (WebSocket)](#6-tutor-chat-websocket)
7. [Conversations](#7-conversations)
8. [Study cards & quizzes](#8-study-cards--quizzes)
9. [Notifications & SSE](#9-notifications--sse)
10. [Complete API catalog](#10-complete-api-catalog)
11. [Feature → endpoint map](#11-feature--endpoint-map)
12. [Recommended frontend architecture](#12-recommended-frontend-architecture)
13. [Build phases (MVP → rich)](#13-build-phases-mvp--rich)
14. [Gaps & workarounds](#14-gaps--workarounds)
15. [Local backend checklist](#15-local-backend-checklist)

---

## 1. Overview

StudyBuddy is a **backend-only** FastAPI app. There is no frontend in this repo — you are building a greenfield student platform that integrates:

| Domain | Student value |
|--------|----------------|
| Identity | Register, login, profile, logout, delete account |
| Library | Upload lecture materials → ingest → searchable knowledge |
| Tutor | Streaming RAG chat grounded in documents + internal memory |
| Study deck | Chapter notes + embedded multiple-choice quizzes |
| Inbox | Know when ingest / study-card jobs finish |

**Live surface:** ~19 HTTP routes + 1 WebSocket + 1 SSE stream + health.

**Happy path:**

```
Register → Upload PDF → Wait for document.status=completed (SSE)
  → Chat about the document (WS)
  → Generate study cards → Read chapters / take quizzes
  → Mark notifications read
```

---

## 2. Architecture the client depends on

```
┌─────────────┐     HTTP / WS / SSE      ┌──────────────┐
│ Student app │ ───────────────────────► │ FastAPI /api │
└─────────────┘                          └──────┬───────┘
                                                │
                    ┌───────────────────────────┼───────────────────────────┐
                    ▼                           ▼                           ▼
               Postgres                    RabbitMQ                      Redis
           (users, docs,              (ingest, cards,              (JWT blacklist,
            chats, cards,              memory extract)              WS caps, SSE)
            notifications)
                    │
                    ▼
         Elasticsearch + Supabase Storage + Gemini (via agents)
```

| Path | What happens |
|------|----------------|
| **Sync** | FastAPI ↔ Postgres for CRUD |
| **Async** | RabbitMQ workers: document ingest, study-card generation, memory extract (internal) |
| **Realtime** | Redis: JWT blacklist, WS connection limits, SSE fan-out |

Agents the UI never calls directly:

- **Chat agent** — driven by `WS /api/chat`
- **Study cards agent** — driven by `POST /api/study-cards/{document_id}` → queue

---

## 3. Response conventions

### Standard envelope (most endpoints)

```json
{
  "data": {},
  "success": true,
  "message": "…",
  "error": null
}
```

### Exceptions

| Surface | Shape |
|---------|--------|
| `GET /api/conversations` | Raw array `[{ id, title }]` |
| `GET /api/conversations/{id}` | Raw detail object (no envelope) |
| WebSocket | `{ type, response?, message?, conversation_id? }` |
| SSE | `event` + `data` JSON `{ type, data }` |

Normalize these in one API client layer.

---

## 4. Authentication & profile

### Token model

1. `POST /register` or `POST /login` → `data.token` (HS256 JWT, `sub` = user id).
2. HTTP: `Authorization: Bearer <token>`.
3. WebSocket: `WS /api/chat?token=<jwt>` (**query param**, not header).
4. Logout / account delete: token written to Redis blacklist until natural expiry.
5. Default TTL: `JWT_EXPIRE_MINUTES` (typically 60). **No refresh tokens.**

### Endpoints

| Method | Path | Auth | Notes |
|--------|------|------|--------|
| `POST` | `/api/authentication/register` | None | `201` — body `{ name, email, password }` → `{ user, token }` |
| `POST` | `/api/authentication/login` | None | Body `{ email, password }` → `{ user, token }` |
| `POST` | `/api/authentication/logout` | Bearer | Blacklists current token |
| `GET` | `/api/users/me` | Bearer | Current profile |
| `PATCH` | `/api/users/me` | Bearer | Partial update; **≥1 field required** |
| `DELETE` | `/api/users/me` | Bearer | Deletes account + cleanup + logout |

### Profile fields

| Field | Register | PATCH |
|-------|----------|--------|
| `name` | Required | Optional (min 3) |
| `email` | Required | Optional |
| `password` | Required | Optional (8–255) |
| `gender` | — | Optional |
| `university` | — | Optional |
| `bio` | — | Optional (≤1500) |
| `timezone` | — | Optional |

`UserResponse`: `id`, `name`, `email`, `gender?`, `university?`, `bio?`, `timezone?`, `created_at`, `updated_at`.

### Client notes

- Persist JWT securely; attach on every HTTP call; clear on 401 / logout.
- Reconnect WebSocket with the same token; force re-login if blacklisted/expired.
- Error codes: `409` email taken, `401` bad credentials.

---

## 5. Document library

Upload is a **3-step pipeline** — do **not** multipart-upload through FastAPI.

### Upload flow

| Step | Call | Action |
|------|------|--------|
| 1 | `POST /api/documents/upload` | Body: `{ name, category, description?, file_name }` → `{ upload_url, path, document }` |
| 2 | `PUT <upload_url>` | Put **raw file bytes** to the signed Supabase URL |
| 3 | `POST /api/documents/{id}/ingest` | `202` — queues RabbitMQ ingest |
| 4 | SSE `document.status` | Track `pending → processing → completed \| failed \| cancelled` |
| 5 | `POST …/ingest/retry` | Only when status is `failed` |

### Allowed files

`.pdf`, `.docx`, `.txt`, `.md`, `.markdown`, `.doc`, `.rtf`, `.odt`, `.epub`  
Extension comes from `file_name`. Default max size ~10 MB.

### Other document APIs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/documents` | Cursor list: `limit` (1–50), `cursor`, `status`, `category`, `name`, `created_after`, `created_before` |
| `GET` | `/api/documents/{id}` | One document |
| `PATCH` | `/api/documents/{id}` | Metadata: `name`, `description`, `category` (≥1 field) |
| `DELETE` | `/api/documents/{id}` | Delete + storage/vectors cleanup |
| `GET` | `/api/documents/download?document_id=` | Signed download URL |

### Document status → UI

| Status | UI | Actions |
|--------|-----|---------|
| `pending` | Queued | Wait |
| `processing` | Spinner | Disable chat-scope / generate-cards |
| `completed` | Ready | Chat, study cards, download |
| `failed` | Error + `comment` | Retry ingest |
| `cancelled` | Muted | Re-upload |

`DocumentResponse` includes: `id`, `name`, `description?`, `category`, `status`, `comment?`, `hash?`, `path?`, `sections?`, `created_at`, `updated_at`.

### Screens to build

- Library grid/list with status filters  
- Upload wizard (name, category, file)  
- Detail drawer (status comment, sections, generate cards)  
- Download action via signed URL  

---

## 6. Tutor chat (WebSocket)

### Connect

```
WS /api/chat?token=<jwt>
```

- Max **5** connections per user  
- Payload ≤ **64 KB**  
- Server greets with heartbeat `Ping`

### Client → server (flat JSON)

```json
{
  "query": "Explain mitosis",
  "conversation_id": "<uuid optional>",
  "document_ids": ["<uuid optional>"]
}
```

| Field | Behavior |
|-------|----------|
| Omit `conversation_id` | Server creates conversation titled `"New Conversation"` |
| `document_ids` | Scope RAG to those materials |
| Legacy `document_id` | Still accepted; coerced to a one-element list |
| `query: "ping"` | Heartbeat `Pong` |

> **Do not** use a `type`/`data` envelope on the client message — that matches stale README docs, not the live router.

### Server → client frames

| `type` | Meaning |
|--------|---------|
| `heartbeat` | Ping / Pong keep-alive |
| `chat.response` | Answer chunk (`response` field) |
| `chat.title` | Auto-generated title (first turn) |
| `chat.done` | Turn finished |
| `chat.error` / `error` | Failure (`message`) |

Most chat frames include `conversation_id`.

### Chat UI checklist

1. Sidebar of conversations; opening one loads history then uses WS.  
2. Optional document multi-select → pass as `document_ids`.  
3. Append `chat.response` chunks into the assistant bubble; finalize on `chat.done`.  
4. Idle ~80s may trigger server Ping — keep the socket alive.  
5. Surface rate-limit copy when `chat.error` says so.

### What the agent does (for UX copy)

```
retrieval decider → rewrite query
  → retrieve documents / memories / conversation history
  → generate response → save chat
  → update summary / store memory → optional title update
```

Memories are **internal** (Elasticsearch). There is no student-facing memory CRUD API.

---

## 7. Conversations

| Method | Path | Response |
|--------|------|----------|
| `GET` | `/api/conversations` | `[{ id, title }]` (raw) |
| `GET` | `/api/conversations/{id}` | `{ id, title, chats: [{ id, conversation_id, query, response, created_at }] }` |

**Missing HTTP:** create (use WS), rename (agent auto-titles), delete.

---

## 8. Study cards & quizzes

Study cards turn a **completed** document into chapters with notes + MCQs. Generation is async.

### Endpoints

| Method | Path | Notes |
|--------|------|--------|
| `POST` | `/api/study-cards/{document_id}` | `202` → `{ document_id }`. **409** if already `success` or in progress. Failed can be regenerated. |
| `GET` | `/api/study-cards/{document_id}` | `{ id, document_id, status, result, created_at, updated_at }` |

`status`: `pending` | `failed` | `success`.

Prefer SSE `study_cards_generated` / `study_cards_failed`, then `GET` once.

### Result shape (`status === "success"`)

```json
{
  "chapters": [
    {
      "chapter_key": "…",
      "introduction": "…",
      "sections": [
        {
          "title": "…",
          "content": "…",
          "references": ["…"],
          "external_references": ["…"]
        }
      ],
      "quiz": [
        {
          "question": "…",
          "options": ["A", "B", "C", "D"],
          "correct_option_index": 0
        }
      ]
    }
  ]
}
```

### Study UX to build

| View | Behavior |
|------|----------|
| Document action | “Generate study cards” when ingest is `completed` |
| Chapter outline | Navigate by `chapter_key`; intro + sections |
| Quiz player | MCQ from `quiz[]`; **score client-side** (no score API) |
| References | Show `references` + `external_references` |
| Failure | Toast on `study_cards_failed`; allow `POST` again |

There is **no list-all-decks** endpoint. Derive decks from the document library (optional `GET` per completed doc).

---

## 9. Notifications & SSE

### REST inbox

| Method | Path | Notes |
|--------|------|--------|
| `GET` | `/api/notifications` | Query: `limit`, `cursor`, `unread_only`, `created_after`, `created_before` |
| `PATCH` | `/api/notifications/read` | Body `{ ids: string[] }` (1–100) |
| `PATCH` | `/api/notifications/{id}/read` | Mark one |

Item: `{ id, title, content, created_at, read_at? }`.

### Live stream

```
GET /api/notifications/stream
Authorization: Bearer <token>
Accept: text/event-stream
```

- Resume with `Last-Event-ID`  
- Idle: `event: ping`  
- Payload: `{ type, data }`

| SSE `type` | When | Client action |
|------------|------|----------------|
| `document.status` | Ingest lifecycle | Update library row; toast on completed/failed |
| `study_cards_generated` | Cards ready | Enable Study view; `GET` cards |
| `study_cards_failed` | Generation exhausted | Show retry CTA |

**Tip:** One authenticated EventSource/fetch-stream per session; fan out to a global store for the unread badge.

---

## 10. Complete API catalog

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| `GET` | `/api/health` | Health check | None |
| `POST` | `/api/authentication/register` | Create account + JWT | None |
| `POST` | `/api/authentication/login` | Login + JWT | None |
| `POST` | `/api/authentication/logout` | Blacklist JWT | Bearer |
| `GET` | `/api/users/me` | Current profile | Bearer |
| `PATCH` | `/api/users/me` | Update profile | Bearer |
| `DELETE` | `/api/users/me` | Delete account | Bearer |
| `POST` | `/api/documents/upload` | Signed upload URL | Bearer |
| `GET` | `/api/documents/download` | Signed download URL | Bearer |
| `POST` | `/api/documents/{id}/ingest` | Queue ingest (`202`) | Bearer |
| `POST` | `/api/documents/{id}/ingest/retry` | Retry failed ingest | Bearer |
| `GET` | `/api/documents` | List documents | Bearer |
| `GET` | `/api/documents/{id}` | Get document | Bearer |
| `PATCH` | `/api/documents/{id}` | Update metadata | Bearer |
| `DELETE` | `/api/documents/{id}` | Delete document | Bearer |
| `GET` | `/api/conversations` | List conversations | Bearer |
| `GET` | `/api/conversations/{id}` | History + messages | Bearer |
| `WS` | `/api/chat?token=` | Streaming tutor | Query JWT |
| `POST` | `/api/study-cards/{document_id}` | Queue generation (`202`) | Bearer |
| `GET` | `/api/study-cards/{document_id}` | Get cards + quiz | Bearer |
| `GET` | `/api/notifications` | List notifications | Bearer |
| `PATCH` | `/api/notifications/read` | Bulk mark read | Bearer |
| `PATCH` | `/api/notifications/{id}/read` | Mark one read | Bearer |
| `GET` | `/api/notifications/stream` | SSE live events | Bearer |

---

## 11. Feature → endpoint map

| Student feature | Endpoints |
|-----------------|-----------|
| Sign up / login / logout | `POST …/register`, `/login`, `/logout` |
| Profile settings | `GET/PATCH/DELETE /api/users/me` |
| Upload materials | `POST /upload` → `PUT` signed URL → `POST …/ingest` |
| Ingest progress | SSE `/notifications/stream` (`document.status`) + list |
| Study chat | `WS /api/chat?token=` |
| Conversation sidebar | `GET /conversations`, `GET /conversations/{id}` |
| Study cards / chapter quizzes | `POST/GET /study-cards/{document_id}` + SSE `study_cards_*` |
| Notification center | `GET /notifications`, `PATCH …/read`, SSE stream |

---

## 12. Recommended frontend architecture

### Modules

| Module | Responsibility |
|--------|----------------|
| `api/http.ts` | Fetch wrapper, Bearer injection, envelope unwrap, 401 handler |
| `api/ws.ts` | Chat socket lifecycle, reconnect, frame dispatch |
| `api/sse.ts` | Notification stream + `Last-Event-ID` resume |
| `stores/session` | User + token |
| `stores/documents` | List cache; patch statuses from SSE |
| `stores/chat` | Active conversation + streaming buffer |
| `stores/studyCards` | Per-document status + result cache |
| `stores/notifications` | Inbox + unread count |

### Route map

**Public**

- `/login`
- `/register`

**Authenticated shell**

- `/library`
- `/library/:id`
- `/chat`
- `/chat/:conversationId`
- `/study/:documentId`
- `/notifications`
- `/settings`

### Env

```bash
VITE_API_BASE_URL=http://localhost:8000/api
# WS: ws://localhost:8000/api/chat?token=...
```

Ensure backend `CORS_ORIGINS` includes the SPA origin.

---

## 13. Build phases (MVP → rich)

| Phase | Ship | Done when |
|-------|------|-----------|
| **P0** | Auth + API client + shell nav | Register / login / logout round-trip |
| **P1** | Upload → ingest → SSE status | PDF reaches `completed` in UI |
| **P2** | Chat WS + conversation sidebar | Grounded Q&A on a document |
| **P3** | Study cards + quiz player | Chapter read + local quiz score |
| **P4** | Notification center + polish | Unread badge + mark read |

**MVP cut:** Auth → Library → Chat → Study cards → Inbox. Defer profile polish and conversation rename until the core loop works.

---

## 14. Gaps & workarounds

| Gap | Impact | Workaround |
|-----|--------|------------|
| No memory CRUD API | Can't show “what tutor remembers” | Omit UI; agent uses memories silently |
| Quiz only inside study-card `result` | No quiz bank / server score | Score in client; optional local history |
| No conversation DELETE / rename HTTP | Sidebar clutter | Hide locally; titles from agent |
| Cards keyed only by `document_id` | No global decks in one call | Derive from document list (careful N+1) |
| Envelope inconsistency | Conversations vs others | Normalize in API client |
| No refresh token | Hard logout after ~60m | Re-login UX; watch `exp` |
| No courses / curriculum | No class hierarchy | Use `category` on documents as a light tag |
| No password reset / OAuth / email verify | Friction | Email/password only for now |

Quiz-related packages may exist in the backend tree but are **not mounted** on the live router — do not call them from the client.

---

## 15. Local backend checklist

1. `docker compose up -d` (Postgres, Redis, RabbitMQ, Elasticsearch, Supabase, Unstructured, …)  
2. `uv sync`  
3. `uv run alembic upgrade head`  
4. Configure `.env` (`DATABASE_URL`, `REDIS_URL`, `RABBITMQ_URL`, `ELASTICSEARCH_URL`, `SUPABASE_*`, `GOOGLE_API_KEY`, `JWT_SECRET`, …)  
5. `uv run python main.py` → default `0.0.0.0:8000`  
6. Open `http://localhost:8000/api/docs`

Workers for ingest / study cards / memory start with the app lifespan.

---

## Appendix A — Example client snippets

### Register + store token

```ts
const res = await fetch(`${API}/authentication/register`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ name, email, password }),
});
const body = await res.json();
const token = body.data.token;
```

### Upload pipeline

```ts
const { data } = await api.post("/documents/upload", {
  name,
  category,
  file_name: file.name,
});

await fetch(data.upload_url, { method: "PUT", body: file });

await api.post(`/documents/${data.document.id}/ingest`);
// wait for SSE document.status === "completed"
```

### Chat WebSocket

```ts
const ws = new WebSocket(`${WS_BASE}/chat?token=${token}`);

ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  switch (msg.type) {
    case "chat.response":
      appendChunk(msg.response);
      break;
    case "chat.done":
      finalizeTurn(msg.conversation_id);
      break;
    case "chat.title":
      updateTitle(msg.conversation_id, msg.response);
      break;
    case "chat.error":
    case "error":
      showError(msg.message);
      break;
  }
};

ws.send(
  JSON.stringify({
    query: "Summarize chapter 2",
    conversation_id: conversationId, // omit to create
    document_ids: selectedDocIds,
  }),
);
```

### SSE notifications

```ts
const es = new EventSource(`${API}/notifications/stream`, {
  // If using fetch-stream + Authorization header instead of EventSource,
  // prefer fetch: EventSource cannot set Bearer headers in browsers.
});
```

Prefer `fetch` + `ReadableStream` with `Authorization: Bearer …` (browser `EventSource` cannot set custom headers). Parse `id` / `event` / `data` lines; on `document.status` and `study_cards_*`, update stores.

---

## Appendix B — Domain entities (quick reference)

| Entity | Storage | Notes |
|--------|---------|--------|
| User | Postgres | Profile fields above |
| Document | Postgres + Supabase + ES | Status machine for ingest |
| Conversation / Chat | Postgres | Created via WS |
| StudyCards | Postgres | Unique per `document_id`; `result` JSONB |
| Notification | Postgres | + Redis SSE |
| Memory | Elasticsearch only | **No public API** |

---

*Generated from the live FastAPI routers in this repository. Prefer `/api/docs` over README when paths or WS protocol disagree.*
