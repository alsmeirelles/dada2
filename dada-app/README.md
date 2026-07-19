# DADA App

Web annotation client for the DADA active-learning platform. The application is
deployed independently from the GPU-backed DADA API and communicates with it
over HTTPS.

## Current status

The initial end-to-end frontend is implemented. The corresponding project,
upload, iteration, lease, statistics, event-ticket, and inference endpoints
must be available in DADA API for live operation. Implementation follows:

- [System architecture](docs/architecture.md)
- [Frontend/API contract](docs/api-contract.md)

Product requirements are recorded in [DESCRIPTION.md](DESCRIPTION.md).

## Local development

Requirements: Node.js 20 or newer and, optionally, Python 3.11 with `uv` for
task orchestration.

```bash
cp .env.example .env
npm install
npm run dev
```

The development App runs at `http://localhost:5173` and expects the API at the
configured `VITE_API_BASE_URL`. Run `npm run lint`, `npm test`, and
`npm run build` before submitting changes. Equivalent Poe tasks are available
through `uv run poe`.

Use `npm run check` to run the complete local quality gate. Browser and release
scenarios are listed in [docs/testing.md](docs/testing.md).

## Production container

The App is a separately deployed static service. Public configuration is
compiled into the JavaScript bundle; `VITE_*` values are not secrets.

```bash
docker build \
  --build-arg VITE_API_BASE_URL=https://api.example.org \
  --build-arg VITE_REALTIME_URL=wss://api.example.org \
  -t dada-app:latest .
docker run --read-only --tmpfs /tmp -p 8080:8080 dada-app:latest
```

The container runs nginx as a non-root user, supports SPA routes, exposes
`/healthz`, sets browser security headers, and caches fingerprinted assets.
The API must allow the deployed App origin through CORS. Terminate TLS at the
container ingress or load balancer.
