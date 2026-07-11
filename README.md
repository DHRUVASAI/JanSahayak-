# JanSahayak Backend (Day 1 MVP)

This backend implements the initial FastAPI skeleton for the JanSahayak project, aligned with `requirements.md`.

## File / Endpoint → Requirement Mapping

- `main.py`
  - **REQ-ARCH-001**: Python + FastAPI backend
  - **REQ-ARCH-011**: API exposure via HTTP
  - **REQ-DEV-006**: OpenAPI/Swagger auto-generated docs
  - **REQ-PERF-011**, **REQ-DEPLOY-013**: `/health` endpoint for uptime checks

- `webhook.py`
  - **REQ-UI-001**: WhatsApp message handling (via Twilio webhook)
  - **REQ-INT-001**: WhatsApp Business API integration

- `routers/chat.py`
  - `/api/v1/chat/message` (POST)
    - **REQ-UI-001**: Text chat handling
    - **REQ-INT-001**: WhatsApp Business API integration
    - **REQ-NLU-001**: Intent recognition placeholder
  - `/api/v1/chat/voice` (POST)
    - **REQ-UI-011**, **REQ-LANG-006**, **REQ-INT-002**: Bhashini voice processing (stub)
  - `/api/v1/chat/image` (POST)
    - **REQ-UI-002**, **REQ-DOC-001**, **REQ-INT-003**: Textract-based OCR (stub)
  - `/api/v1/chat/history/{userId}` (GET)
    - **REQ-DATA-002**, **REQ-ARCH-006**: Firestore history (stub)
  - `/api/v1/chat/session/{sessionId}` (DELETE)
    - **REQ-NLU-003**, **REQ-DATA-010**: Session/context cleanup (stub)

- `routers/documents.py`
  - `/api/v1/document/upload` (POST)
    - **REQ-DOC-001**, **REQ-DATA-003**, **REQ-ARCH-008**, **REQ-INT-003**
  - `/api/v1/document/textract` (POST)
    - **REQ-DOC-001**, **REQ-DOC-011**, **REQ-INT-003**
  - `/api/v1/document/verify/{documentId}` (GET)
    - **REQ-DOC-007**, **REQ-DOC-008**, **REQ-GOV-001**
  - `/api/v1/document/validate` (POST)
    - **REQ-DOC-008**, **REQ-GOV-001**, **REQ-INT-008**
  - `/api/v1/document/{documentId}` (DELETE)
    - **REQ-SEC-001**, **REQ-SEC-002**, **REQ-DOC-010**

- `routers/applications.py`
  - `/api/v1/application/submit` (POST)
    - **REQ-GOV-001**, **REQ-GOV-004**, **REQ-INT-006**, **REQ-INT-008**
  - `/api/v1/application/status/{applicationId}` (GET)
    - **REQ-GOV-011**, **REQ-GOV-013**
  - `/api/v1/application/history/{userId}` (GET)
    - **REQ-DATA-006**, **REQ-DATA-011**
  - `/api/v1/application/appeal` (POST)
    - **REQ-GOV-015**
  - `/api/v1/application/receipt/{applicationId}` (GET)
    - **REQ-GOV-014**

- `routers/schemes.py`
  - `/api/v1/schemes/list` (GET)
    - **REQ-DATA-006**, **REQ-SUCCESS-015**
  - `/api/v1/schemes/{schemeId}` (GET)
    - **REQ-DATA-006**, **REQ-DATA-009**
  - `/api/v1/schemes/eligibility` (POST)
    - **REQ-DATA-010**, **REQ-NLU-001**
  - `/api/v1/schemes/search` (GET)
    - **REQ-DATA-010**, **REQ-SUCCESS-015**
  - `/api/v1/schemes/recommendations/{userId}` (GET)
    - **REQ-DATA-010**, **REQ-SUCCESS-015**

- `models/user.py` (`UserProfile`)
  - **REQ-DATA-001** – Firebase Authentication user profile
  - **REQ-DATA-002** – Firestore schema
  - **REQ-ARCH-006** – Database model alignment

- `models/application.py` (`ApplicationRecord`)
  - **REQ-GOV-011**, **REQ-DATA-006**, **REQ-ARCH-006**

- `models/message.py` (`ChatMessage`)
  - **REQ-UI-001**, **REQ-INT-001**, **REQ-NLU-001**

- `services/`
  - Placeholder for business logic services
  - Will host integrations for Bhashini, Textract, Firebase, RPA agents

## API Route Tree (Day 1)

Base URL: `/`

- `GET /health`
- `POST /webhook` — Twilio WhatsApp webhook (echo via chat processor)

API v1:

- `/api/v1/chat`
  - `POST /api/v1/chat/message`
  - `POST /api/v1/chat/voice`
  - `POST /api/v1/chat/image`
  - `GET /api/v1/chat/history/{userId}`
  - `DELETE /api/v1/chat/session/{sessionId}`

- `/api/v1/document`
  - `POST /api/v1/document/upload`
  - `POST /api/v1/document/textract`
  - `GET /api/v1/document/verify/{documentId}`
  - `POST /api/v1/document/validate`
  - `DELETE /api/v1/document/{documentId}`

- `/api/v1/application`
  - `POST /api/v1/application/submit`
  - `GET /api/v1/application/status/{applicationId}`
  - `GET /api/v1/application/history/{userId}`
  - `POST /api/v1/application/appeal`
  - `GET /api/v1/application/receipt/{applicationId}`

- `/api/v1/schemes`
  - `GET /api/v1/schemes/list`
  - `GET /api/v1/schemes/{schemeId}`
  - `POST /api/v1/schemes/eligibility`
  - `GET /api/v1/schemes/search`
  - `GET /api/v1/schemes/recommendations/{userId}`

## Day 1 MVP Scope

**Working behavior**

- `/health` returns a simple JSON health check.
- `/webhook` accepts Twilio WhatsApp POST (form field `Body`) and:
  - wraps the payload into a `ChatMessage`
  - calls the shared `process_text_message` in `routers/chat.py`
  - returns TwiML XML with an `Echo: <message>` response
- `/api/v1/chat/message` returns the same echo response as JSON.

**Stubbed / to be implemented**

- Voice handling (`/api/v1/chat/voice`) – Bhashini ASR + TTS
- Image/document handling (`/api/v1/chat/image`, `/api/v1/document/*`) – Textract + validation
- Application submission and tracking (`/api/v1/application/*`)
- Scheme search and recommendations (`/api/v1/schemes/*`)
- Firebase integrations for user profiles, history, documents
- Security (auth, RBAC, rate limiting) and analytics hooks

## Setup Instructions

From `backend/` directory:

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then open Swagger UI:

```text
http://localhost:8000/docs
```

You should see all routes defined above.

## Twilio + ngrok (WhatsApp Sandbox)

1. Start the backend:

```bash
uvicorn main:app --reload --port 8000
```

2. Start `ngrok` tunnel:

```bash
ngrok http 8000
```

3. In Twilio Console → Messaging → Try it out → Send a WhatsApp message:
   - Join the sandbox as instructed by Twilio.
   - Set the **Webhook URL** to:

   ```text
   https://YOUR_NGROK_URL/webhook
   ```

   - Method: `POST`

4. Send a message to the WhatsApp sandbox number — you should receive:

```text
Echo: <your message>
```

