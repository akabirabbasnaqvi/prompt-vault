# PromptVault

PromptVault is an AI prompt lifecycle management API for versioning, organizing, testing, and evaluating prompts in a production-style workflow.

## What it does

- Manage workspaces and prompts through a REST API
- Track prompt evaluation jobs with background Celery workers
- Cache prompt data in Redis for faster reads
- Store data in PostgreSQL with Alembic migrations
- Expose health and status endpoints for service monitoring
- Run locally with Docker Compose and continuously verify builds with GitHub Actions

## Tech Stack

- FastAPI
- PostgreSQL
- Redis
- Celery
- SQLAlchemy 2.x
- Alembic
- Docker
- GitHub Actions
- pytest

## Project Structure

- `app/main.py` - FastAPI entry point, lifespan, health checks, and router registration
- `app/api/v1/` - Workspace, prompt, and evaluation routes
- `app/services/` - Business logic for CRUD, caching, and evaluation jobs
- `app/models/` - SQLAlchemy ORM models
- `app/schemas/` - Pydantic request and response models
- `app/core/` - Configuration and Redis cache helpers
- `app/db/` - Database base and session setup
- `app/worker/` - Celery app and background task implementation
- `alembic/` - Database migrations
- `dags/` - Airflow DAGs for scheduled workflows
- `tests/` - Unit and integration tests

## API Highlights

- `GET /` - service welcome message
- `GET /health` - database and Redis health check
- `GET /api/v1/status` - API version status
- `POST /api/v1/workspaces/` - create a workspace
- `GET /api/v1/workspaces/` - list workspaces
- `POST /api/v1/workspaces/{slug}/prompts/` - create a prompt
- `GET /api/v1/workspaces/{slug}/prompts/` - list prompts in a workspace
- `POST /api/v1/workspaces/{slug}/prompts/{prompt_slug}/evaluate` - create an evaluation job
- `GET /api/v1/jobs/{job_id}` - check evaluation job status

## Quick Start

Start the full stack with Docker:

```bash
docker compose up --build
```

Then open:

- API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Testing

Run the full test suite:

```bash
pytest
```

Run only unit tests:

```bash
pytest tests/unit/ -v
```

Run only integration tests:

```bash
pytest tests/integration/ -v
```

Run a single test file:

```bash
pytest tests/unit/test_schemas.py -v
```

Run one specific test:

```bash
pytest tests/unit/test_schemas.py::TestWorkspaceCreateSchema::test_valid_workspace_create -v
```

## Coverage

Pytest is already configured to generate coverage output and an HTML report in `htmlcov/`.

Open the report at:

```text
D:\PromptVault(Project)\htmlcov\index.html
```

## Local Development Notes

- PostgreSQL runs on host port `5433`
- Redis runs on host port `6380`
- The API expects `DATABASE_URL` to point to PostgreSQL
- The worker uses the same codebase and environment variables as the API

## Migrations

Apply database migrations with Alembic:

```bash
alembic upgrade head
```

## CI/CD

The repository includes GitHub Actions for:

- running tests against PostgreSQL and Redis service containers
- building the Docker image to verify the container configuration

## Notes

- Replace `YOUR_USERNAME` in any badge URLs with your GitHub username.
- The test suite still uses a dedicated PostgreSQL test database and real ORM models, so it is not fully database-free.