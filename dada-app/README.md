# DADA App

Web annotation client for the DADA active-learning platform. The application is
deployed independently from the GPU-backed DADA API and communicates with it
over HTTPS.

## Current status

The project is in its contract and architecture phase. Implementation must
follow the documents below:

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
