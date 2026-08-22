# Goals

The project should provide a complete active learning solution for the main Computer Vision tasks: classification,
detection and segmentation.

The project is divided between an application (dada-app) frontend and the API (dada-api).

This is engineered to be an easy-install/easy-use solution for either developers or annotators.
# Project Structure

```
DADA/
│
├── dada-api/                  # Backend Application Package
│   ├── dada_api/
│   │   ├── __init__.py
│   │   ├── main.py            # FastAPI main loop
│   │   ├── storage.py         # AbstractStorageProvider
│   │   └── models/            # Pluggable ML Model Wrappers
│   ├── pyproject.toml
│   └── README.md
│
├── dada-app/                  # Frontend Application Package
│   ├── src/                   # TypeScript/React source code
│   ├── public/
│   ├── package.json           # Node configuration (Fabric.js, Tailwind, etc.)
│   ├── vite.config.ts
│   └── pyproject.toml         # Python automation tasks wrapper
│
└── .gitignore
```

# DADA API

Should implement a running FastAPI server containerized in a docker image. It should handle multiple parallel requests and 
store annotation data for different datasets.


# DADA APP

A web frontend also containerized as docker image(s). Should serve multiple users producing data annotations.

Refer to the specific README in the package folder.

## Run the current local baseline

The App and API can be run locally now for browser-based login and frontend
validation. The API currently implements Phases 0 and 1: service foundation,
health/readiness, administrator bootstrap, login, refresh-session support, and
project-role authorization. Project creation, uploads, annotation queues,
consensus resolution, and review endpoints are planned but are not live yet.

The App already contains the corresponding user interfaces, including the
single/consensus setup controls and manager consensus screens. Those screens
become functional as their Phase 2+ API endpoints are delivered; they should
currently be treated as contract-driven frontend work rather than a complete
end-to-end annotation demo.

### Prerequisites

- Python 3.11 or newer and [uv](https://docs.astral.sh/uv/)
- Docker Engine with Compose v2
- Node.js 20 or newer and npm

### 1. Start the API and local infrastructure

Open one terminal from the repository root:

```bash
cd dada-api
cp .env.example .env
```

Edit `dada-api/.env` before exposing the services outside your machine. At a
minimum, replace `DADA_JWT_SECRET_KEY` and
`DADA_SEED_ADMIN_PASSWORD`. For this plain-HTTP local setup, set:

```dotenv
DADA_REFRESH_COOKIE_SECURE=false
```

Then install dependencies, start PostgreSQL and Redis, migrate the database,
create the initial administrator, and start the API:

```bash
make sync-dev
make infra-up
make migrate
make bootstrap-admin
make run
```

Keep `make run` running. It serves the API at
<http://localhost:8000>. Verify the baseline in another terminal or browser:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Interactive API documentation is available at <http://localhost:8000/docs>.
The bootstrap command uses the `DADA_SEED_ADMIN_USERNAME` and
`DADA_SEED_ADMIN_PASSWORD` values from `.env`; use those same credentials on
the App login screen. It is safe to rerun for the same administrator.

### 2. Start the browser App

Open a second terminal from the repository root:

```bash
cd dada-app
cp .env.example .env
npm install
npm run dev
```

`dada-app/.env.example` already targets `http://localhost:8000`; leave
`VITE_API_BASE_URL` unchanged for this local setup. Open
<http://localhost:5173> in Chrome or Firefox and log in with the bootstrap
administrator credentials.

The following are expected to work today:

- the App loads at the login page;
- login calls the live API and protects browser routes with the issued access
  token;
- `/health`, `/ready`, `/docs`, `/api/v1/auth/token`, and
  `/api/v1/auth/me` are available from the API;
- the built App can be checked with `npm run lint`, `npm test`, and
  `npm run build`.

The Projects page currently reports that projects are unavailable because
`GET /api/v1/projects` intentionally returns `501` until API Phase 2. Do not
expect project creation, uploads, annotation workspace, consensus review, or
active-learning flows to complete against the current API yet. This is the
correct current behavior, not a browser configuration failure.

### Stop local services

Stop the development servers with `Ctrl+C`. To stop PostgreSQL and Redis while
preserving their local data:

```bash
cd dada-api
make infra-down
```

The Compose volume is deliberately retained. Removing it deletes the local
database and is not part of the normal workflow.

For package-specific details, see the [App README](dada-app/README.md),
[API README](dada-api/README.md), and the
[combined implementation plan](dada-api/docs/api-implementation-plan.md).
