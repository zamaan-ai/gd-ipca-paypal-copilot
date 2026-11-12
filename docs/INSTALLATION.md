# GD-IPCA Mark 2 — Installation & Setup Guide

This document describes how to deploy and run the **Goal-Driven Intent-to-Portfolio Compilation Engine (GD-IPCA Mark 2)** in local development, hybrid Docker, and production environments.

---

## Prerequisites

- **Python**: 3.11+
- **Node.js**: 20+ (with npm 10+)
- **MySQL**: 8.0+ (Optional for local dev — engine features auto-fallback to SQLite)
- **Redis**: 7.0+ (Optional for local dev — engine features auto-fallback to in-memory cache)
- **Docker & Docker Compose**: (Required for containerized deployment)

---

## 1. Quick Start (Local Development)

### Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt email-validator

# Run database migrations
python -m alembic upgrade head

# Start FastAPI development server
uvicorn app.main:app --reload --port 8000
```

The interactive OpenAPI documentation is available at:
`http://localhost:8000/api/docs`

### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## 2. Production Docker Deployment

To launch the full production stack (MySQL 8.0 + Redis 7 + FastAPI Multi-Worker + Nginx React Frontend):

```bash
# From the project root directory
docker compose up --build -d
```

### Services Deployed:
| Container | Port | Service Description |
|-----------|------|---------------------|
| `gdipca_frontend` | `80` | Nginx reverse proxy + React SPA |
| `gdipca_backend` | `8000` | FastAPI 4-worker Uvicorn application |
| `gdipca_mysql` | `3306` | MySQL 8.0 with persistent storage |
| `gdipca_redis` | `6379` | Redis 7 in-memory cache with AOF persistence |

---

## 3. Seed Accounts & Credentials

The system initializes two default user accounts on startup:

| Role | Email | Password |
|------|-------|----------|
| **Demo Investor** | `demo@gdipca.io` | `Demo12345!` |
| **Administrator** | `admin@gdipca.io` | `Admin12345!` |

---

## 4. Running Automated Tests

### Backend Test Suite (Pytest)
```bash
cd backend
python -m pytest tests/ -v
```

### Frontend Unit Tests (Node Test Runner)
```bash
cd frontend
npm test
```

### Production Build Verification
```bash
cd frontend
npm run build
```

### Runtime Health & Smoke Verification
```bash
python backend/scripts/verify_deployment.py
```

---

## 5. Database Backup & Restore

```bash
# Create automated backup
python backend/scripts/backup_restore.py

# Restore from backup file
python backend/scripts/backup_restore.py restore <path_to_backup_file>
```
