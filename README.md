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