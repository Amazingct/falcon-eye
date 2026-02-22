# Plan / TODO: Standard Media Messages + `query_record` Tool

## Goal

Introduce a **standard message type** for delivering & receiving media files in chat across:

- **Dashboard UI** (agent chat + chatbot chat)
- **AI/LLM input** (media messages become regular `user` / `assistant` text messages for context)
- **Telegram adapter** (media messages become Telegram attachments)

This plan covers:

1. **Two new roles**: `assistant_media`, `user_media`
2. **Structured `content`** payload for media messages
3. **UI rendering** rules (WhatsApp-style inline media, plus downloads)
4. **AI ↔ UI conversions** for sending/receiving media
5. A **new tool**: `query_record` that returns an `assistant_media` message

---

## New Roles

Add two new roles, used by both chatbot sessions and agent sessions:

- `assistant_media`
- `user_media`

### Semantics

- `assistant_media`: produced by AI/tooling to deliver media to the human.
- `user_media`: produced when a human uploads/attaches media in the UI/Telegram.

### Compatibility expectations

- Existing roles remain unchanged: `user`, `assistant`, `system`.
- Existing text messages continue to use `content: string`.
- New media roles use `content: object` (structured payload defined below).

---

## Media Message `content` Schema (canonical)

For `assistant_media` / `user_media`, `content` MUST be an object with this shape:

```json
{
  "general_caption": "a caption for media files attached",
  "media": [
    {
      "name": "some name",
      "cam": {
        "cam_id": "uuid-if-originated-from-a-cam",
        "name": "camera name",
        "location": "camera location",
        "any_other_cam_info": "allowed"
      },
      "timestamps": "some time/date or range",
      "caption": "caption",
      "path": "media url/path that frontend can access",
      "type": "file extension (jpeg, mp4, mp3, pdf, ...)"
    }
  ]
}
```

### Field rules

- `general_caption`: `string | null`
- `media`: non-empty array (prefer), each item:
  - `name`: `string | null`
  - `cam`: `object | null`
    - MUST allow additional camera metadata keys beyond `cam_id` and `name`.
  - `timestamps`: `string | object | null`
    - **Recommended**: use ISO-8601 strings (or `{start,end}`) for easy rendering/filtering.
  - `caption`: `string | null`
  - `path`: `string` (must be **directly loadable/downloadable** by the dashboard)
  - `type`: `string` (lowercase extension preferred: `jpg`, `jpeg`, `png`, `webp`, `gif`, `mp4`, `webm`, `mp3`, `wav`, `pdf`, ...)

### Message envelope (common fields)

Regardless of role, messages still carry the “normal” metadata:

- `id`
- `session_id` (and `agent_id` for agent chat)
- `role`
- `created_at`
- `source`, `source_user` (agent chat)
- token usage fields (agent chat)

---

## Storage Plan (DB + ORM)

Falcon-Eye currently has **two message tables**:

- Chatbot: `chat_sessions`, `chat_messages` (`ChatMessage.content` is `Text`)
- Agents: `agent_chat_messages` (`AgentChatMessage.content` is `Text`)

Because media messages require structured content, we need a safe migration plan.

### Recommended approach (explicit typed payload)

Add new columns (both message tables):

- `content_type`: `text | media` (string enum, default `text`)
- `content_text`: `Text` (nullable; for text messages)
- `content_media`: `JSONB` (nullable; for media messages)

And keep old `content` temporarily for backwards compatibility, then remove later.

**Why**: avoids ambiguous “sometimes JSON string” in a `Text` column and keeps queries sane.

### Minimal-change alternative (not preferred)

Keep `content` as `Text` and store media content as JSON string when `role in {assistant_media,user_media}`.

**Downside**: schema is implicit, decoding required everywhere, harder to validate.

### Migration TODO

- Add columns to both tables.
- Backfill:
  - set `content_type='text'`, `content_text=content` for existing rows
- Update `to_dict()`:
  - if `content_type=='media'`: output `content` as object
  - else: output `content` as string
- Keep write paths dual-writing until frontend + adapters updated, then remove old `content`.

---

## API / DTO Plan

### Unified message JSON

Return a consistent envelope from API endpoints, but allow:

- `content: string` for text roles
- `content: object` for media roles

This matches the requirement and keeps UI detection simple.

### Endpoints impacted

- Agent chat:
  - `POST /api/chat/{agent_id}/send`
  - `POST /api/chat/{agent_id}/messages/save`
  - `GET /api/chat/{agent_id}/history`
- Chatbot sessions:
  - `POST /api/chat/sessions/{session_id}/chat`
  - `GET /api/chat/sessions/{session_id}`
  - `GET /api/chat/sessions`

### Validation TODO

Introduce Pydantic models that can validate:

- `role` enum includes new roles
- `content` union: `str | MediaContent`
- `MediaContent` enforces `path` and `type` for each media item

---

## UI Plan (Dashboard)

### Detection rules

The UI should treat a message as “media message” if either:

- `role` is `assistant_media` or `user_media`, OR
- `typeof content === 'object'` and `content.media` is an array (future-proofing)

### Rendering requirements (WhatsApp-like)

- **Images** (`jpg`, `jpeg`, `png`, `webp`, `gif`):
  - render thumbnail (click to open full)
- **Video** (`mp4`, `webm`, `mov` if supported):
  - render inline player with controls
- **Audio** (`mp3`, `wav`, `m4a`):
  - render `<audio controls>`
- **Other files**:
  - render downloadable “file card” (name, type, size if available, download link)

Caption rules:

- show `general_caption` above/below the media grid
- show per-item `caption` on each item (if present)

Camera attribution rules:

- if `cam` exists, show camera name/location badge
- if `timestamps` exists, show a timestamp badge (formatted)

### URL accessibility requirement

`path` must be a URL the browser can fetch. Decide one canonical convention:

- If it lives in shared filesystem (snapshots, generated artifacts):
  - use an API URL like `/api/files/read/<path>` (binary-friendly)
- If it’s a recording:
  - use `/api/recordings/<id>/download` or a new “recording URL” endpoint

Add a small helper in frontend to convert server “paths” into absolute URLs if needed.

---

## AI ↔ Media Message Conversion

### Feeding history into the LLM

When building `llm_messages` (OpenAI/Anthropic-style list), **media roles must be converted** to standard roles:

- `user_media` → `role: "user"`
- `assistant_media` → `role: "assistant"`

And their structured content must be converted into a text summary, for example:

- Include `general_caption` (if any)
- List each item:
  - camera info, timestamps, caption, and *the URL/path*

Important: do **not** embed raw binary; only references/URLs + captions/metadata.

### AI producing media for humans

To make it easy/reliable for the AI to output structured media messages, introduce a **dedicated tool call** that accepts the `assistant_media` payload as parameters, persists it, and routes it to the active channel(s).

We need a single internal way for AI/tooling to “emit” media messages:

- The tool layer (`query_record`, etc.) should be able to create an `assistant_media` message in chat history via a tool call.
- The message must be **automatically routable**:
  - **Dashboard UI**: appears in the current session history (and optionally returned inline in the send response)
  - **Telegram**: emitted as Telegram attachments (photo/video/audio/document)

This implies we should prefer “message-as-data” rather than “string response + separate media side-channel”.

---

## New Tool: `deliver_media_message` (AI-friendly structured output)

### Purpose

Let the AI produce a structured `assistant_media` message via a tool call, rather than trying to format JSON inside free-form text.

### Parameters (conceptual)

- `session_id` (optional): defaults to **current chat session** from agent context
- `general_caption` (`string | null`)
- `media` (`array` of items):
  - `name` (`string | null`)
  - `cam` (`object | null`) including `cam_id` when applicable
  - `timestamps` (`string | object | null`)
  - `caption` (`string | null`)
  - `path` (`string`) — must be browser-accessible URL/path
  - `type` (`string`) — extension (`jpeg`, `mp4`, etc.)
- Optional routing flags:
  - `deliver_to_dashboard` (`bool`, default true)
  - `deliver_to_telegram` (`bool`, default true if agent/channel is telegram)

### Behavior

- **Persist** an `assistant_media` message into the current session history.
- **Dashboard**:
  - Primary delivery mechanism is that the UI reads history and renders the media message.
  - Optional improvement: also return the full structured message in the `/send` response so UI can render immediately without polling/refresh.
- **Telegram**:
  - Convert each media item to the appropriate Telegram attachment call.
  - Use per-item caption when available, else fall back to `general_caption`.

### Tool return value

Return a simple acknowledgement string suitable for the LLM, e.g.:

- `"Delivered 3 media item(s) to session <session_id>."`

This allows the main assistant text response to stay minimal (or even empty), while the UI receives the media content via persisted message history / channel delivery.

## Telegram Adapter Plan

Telegram should map `assistant_media` to Telegram attachments:

- image → `sendPhoto`
- video → `sendVideo`
- audio → `sendAudio` (or `sendDocument` depending on needs)
- unknown → `sendDocument`

Caption:

- Prefer per-item caption (Telegram has per-message caption limits)
- Fall back to `general_caption`

Inbound (user → system):

- Telegram attachment becomes `user_media` with:
  - `path` pointing to a stored, fetchable file (saved into shared filesystem or object storage)
  - `type` inferred from Telegram mime/filename
  - `name` from filename if present

---

## New Tool: `query_record`

### Purpose

Answer a natural-language query about historical recordings/snapshots and return an `assistant_media` message:

Example: “when did you see my dog last” → returns images/video clips + metadata.

### Inputs

- `query` (string): the question/request
- Optional filters:
  - `cam_ids` (string[])
  - `cam_locations` (string[])
  - `start_time` (string, ISO-8601)
  - `end_time` (string, ISO-8601)

### Output

- MUST produce a message with `role="assistant_media"` and `content` matching the canonical schema.
- Should also include normal message metadata (source, timestamps).

### Output mechanism (preferred)

- `query_record` should internally call (or share code with) `deliver_media_message` so the AI/tooling doesn’t have to “manually” format or persist media messages.

### Implementation plan (phased)

**Phase 1 (metadata + links)**:

- Query the recordings table within optional filters.
- Return a set of relevant recordings as media items (likely `mp4`) with:
  - `cam` info
  - `timestamps` range (start/end)
  - `path` = browser-downloadable URL
  - `type` = `mp4`
  - optional captions (“Recording: Front Door (10:30–10:45)”)

**Phase 2 (thumbnails / previews)**:

- Generate 1–3 preview frames per recording, store them in shared filesystem, return as `jpg` items.

**Phase 3 (semantic vision search)**:

- Sample frames from candidates and use vision model classification to answer queries like “dog last seen”.
- Return the best matching frames/clips in `assistant_media`, plus a short textual explanation either as:
  - a separate `assistant` message, or
  - `general_caption` in the media message.

### Integration points TODO

- Tool registry:
  - Add `query_record` schema to `scripts/cam-manager-py/app/tools/registry.py`
- Tool handler:
  - Implement `query_record` in `scripts/cam-manager-py/app/tools/handlers.py`
- Tool execution response:
  - Decide how tools can emit structured messages (not only string + `media[]` side-channel)
- Chat persistence:
  - Save the resulting `assistant_media` message into the active chat session (agent chat and/or chatbot session)

---

## Detailed TODO Checklist

### Backend (DB / models / API)

- **Roles**
  - Extend allowed roles enum/validation everywhere to include `assistant_media`, `user_media`.
- **DB schema**
  - Add `content_type`, `content_text`, `content_media` to:
    - `ChatMessage`
    - `AgentChatMessage`
  - Write lightweight migration / `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...`
  - Backfill existing rows.
- **Serialization**
  - Update `to_dict()` to output `content` as `string | object`.
- **Chat history → LLM messages**
  - Convert media roles into regular `user`/`assistant` roles with text summaries.
- **API contracts**
  - Update chat endpoints to accept/save `user_media` uploads (later) and return `assistant_media`.

### Frontend (Dashboard)

- **Message typing**
  - Add a robust media-message detector.
- **Renderer**
  - Add UI components for:
    - image grid + lightbox
    - video player
    - audio player
    - file card download
  - Show captions + camera/timestamp badges.
- **Back-compat**
  - Keep rendering text messages unchanged.

### Agent pod / adapters

- **Telegram outbound**
  - Convert `assistant_media` to Telegram attachment sends.
- **Telegram inbound**
  - Convert user attachments to `user_media` and persist.

### Tooling

- **`query_record` tool**
  - Add tool definition + handler
  - Implement Phase 1 first (recording metadata + download links)
  - Evolve to Phase 2/3 as needed

### Testing / QA

- Unit tests for message serialization (`content` union).
- Frontend manual QA checklist:
  - images/videos/audio display
  - downloads work
  - mixed text+media ordering works
  - history reload renders correctly
  - Telegram send/receive works

