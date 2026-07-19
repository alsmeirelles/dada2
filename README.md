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