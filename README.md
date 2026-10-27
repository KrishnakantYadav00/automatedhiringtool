# Automated Hiring Platform — M1 Sourcing Engine

The **M1 Sourcing Engine** aggregates candidate profiles from **Naukri, Shine, LinkedIn, and Email Inboxes (IMAP)**, normalizes attributes, executes exact & fuzzy deduplication, and pushes candidate records into **CEIPAL ATS**.

---

## Architecture Overview

```
[Naukri / Shine / LinkedIn / Email]
                 │
                 ▼
       [BaseConnector Stream]
                 │
                 ▼
       [CandidateNormalizer]   ── (Phone E.164, Title casing, City canonicalization)
                 │
                 ▼
      [DeduplicationEngine]   ── (Exact hash/email/phone + RapidFuzz fuzzy match)
                 │
         ┌───────┴────────┐
         ▼                ▼
   [New Profile]    [Merged Record]
         │                │
         └───────┬────────┘
                 ▼
       [PostgreSQL Database]
                 │
                 ▼
        [CEIPAL ATS Client]
```

---

## Quick Start with Docker

### 1. Configure Environment
Copy the example environment file:
```bash
cp .env.example .env
```
Fill in your credentials for IMAP, Naukri, Shine, LinkedIn, and CEIPAL as appropriate.

### 2. Start Services
Run all services (PostgreSQL 16, Redis 7, and the FastAPI Sourcing microservice) using Docker Compose:
```bash
docker compose up --build -d
```

### 3. Verify Health & Interactive Docs
- **Interactive Swagger Docs**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **ReDoc**: [http://localhost:8001/redoc](http://localhost:8001/redoc)
- **Liveness probe**: `GET http://localhost:8001/health`

---

## API Endpoints Summary

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/sourcing/trigger/{source}` | Trigger a specific connector (`email`, `naukri`, `shine`, `linkedin`) |
| `POST` | `/api/v1/sourcing/trigger/all` | Trigger all configured connectors sequentially |
| `GET` | `/api/v1/sourcing/candidates` | List normalized candidates (paginated, with search & status filters) |
| `GET` | `/api/v1/sourcing/candidates/{id}` | Detailed candidate profile with all linked source platform records |
| `GET` | `/api/v1/sourcing/stats` | Aggregated metrics (total candidates, duplicates merged, push rates) |
| `GET` | `/api/v1/sourcing/health` | Health checks for all connectors, DB, and CEIPAL |
| `POST` | `/api/v1/sourcing/ceipal/push` | Batch push candidate records into CEIPAL |
| `POST` | `/api/v1/sourcing/webhook/ceipal` | Inbound status confirmation webhook from CEIPAL |

---

## Running Automated Tests

```bash
cd services/sourcing
pytest tests/ -v
```
