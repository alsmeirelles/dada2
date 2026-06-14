# DADA Evolution System
Data Aware Data Acquisition (DADA) is an Active Learning solution that combines uncertainty and representativeness to select anotation images.

## Technical Specification & Architecture Blueprint

This document outlines the architectural decisions, system requirements, and technical implementation path for a custom, enterprise-grade, collaborative instance segmentation tool integrated into an Active Learning (AL) pipeline.

---

## 1. System Overview & Core Objectives

The ASAL platform is designed to eliminate the primary bottleneck in computer vision: the high cost of manual pixel-level segmentation. By coupling a high-performance interactive frontend canvas with a robust, asynchronous Python backend, the system orchestrates a continuous active learning loop. 

### Key Capabilities
* **Interactive Assisted Segmentation:** Leverages **Segment Anything Model (SAM 3.1)** on the backend to transform point-clicks and bounding boxes from the frontend into precise multi-polygon instances instantly.
* **Multi-User Queue Orchestration:** A centralized backend state engine manages an unlabeled data pool, dispatching optimal items to distributed annotators upon clicking a unified "Next Image" control.
* **Active Learning Loop:** Implements model-in-the-loop uncertainty sampling strategies to select high-entropy or low-confidence samples for human review, maximizing the valuation of every single user mutation.
* **Fully Open-Source / Zero-License Overhead:** Built entirely on permissive open-source technologies (MIT, Apache 2.0, BSD) avoiding commercial license dependencies.

---

### Conventions
* **Tests:** All unit tests are written in **Pytest** and run via **GitHub Actions**.
* **Naming:** All classes, functions, and variables are named in **CamelCase** with **snake_case** for constants and **PascalCase** for enums.
* **Documentation:** All classes, functions, and variables are documented with **Google-style docstrings**.

---

## 2. Technical Stack & Decision Matrix

### Frontend Canvas & Application Layer
* **Language:** TypeScript (Strict Mode)
* **Framework:** **Vite + React** or **Vite + Vue 3** (Pinia/Redux for clean state boundaries)
* **Canvas Engine:** **Fabric.js v6** or **Konva.js**
  * *Rationale:* Pure HTML-over-the-wire or low-code Python frontends hit serious performance bottlenecks when serializing mouse-tracking vectors or handling real-time high-density coordinate payloads over WebSockets. A dedicated client-side 2D engine allows responsive panning, zooming, vector anchor transformation, and multi-layered rendering natively inside the client's rendering pipeline.
* **UI Components & Icons:** **Tailwind CSS** + **Lucide React / Lucide Vue** + **Shadcn UI**
  * *Rationale:* Modern, clean, professional, and completely free styling ecosystem providing responsive, highly semantic components out-of-the-box.

### Backend Infrastructure
* **Core Framework:** **FastAPI (Python 3.11+)**
  * *Rationale:* Asynchronous request lifecycle natively built for handling fast, parallel high-concurrency API demands, integrated with Pydantic for rigid runtime contract verification.
* **Task Worker Queue:** **Celery** or **ARQ** backed by **Redis**
  * *Rationale:* Heavy ML operations (SAM inference, batch fine-tuning) cannot block the HTTP worker pool. These are strictly offloaded into isolated worker processes.
* **Persistence Layer:** **PostgreSQL** with **PostGIS** extension
  * *Rationale:* Instead of saving masks as heavy, opaque binary arrays (bitmaps) which saturate database throughput and break analytics, masks are converted to standard **COCO-style floating-point polygons** or compact **Run-Length Encoding (RLE)** strings and kept in indexed geometric tables.

---

## 3. Data Flow & Active Learning Architecture

```
                                 [ Unlabeled Pool ]
                                         │
                                         ▼
   [ User App ] ───(Next Image)───> [ FastAPI ] ───(Query Strategy)───┐
        ▲                                                             │
        │ (Dispatches Image)                                          ▼
   ┌────┴──────────────────────── [ PostgreSQL ] <───────────── [ ML Workers ]
   │                                     ▲                            ▲
   ▼                                     │                            │
[ Canvas UI ] ───(Submit Polygons)───────┘                            │
   │                                                                  │
   └─────────────(Every N Images / Batch Trigger)─────────────────────┘
```

### 3.1 Role-Based Access Control (RBAC) & Configuration
The system enforces a lightweight JWT-based authentication layer defining two core roles:
* `annotator`: Accesses the data queue, pulls images via the "Next Image" service, and submits polygons.
* `admin`: Accesses system monitoring dashboards and can mutate Active Learning execution parameters at runtime (e.g., change the uncertainty sampling strategy, adjust the background batch retraining size, or trigger an immediate model checkpoint compilation).

```
[Client App] ──(JWT Token)──> [FastAPI Middleware] ──(Check Scopes)──> Route Handler
├── /admin/* (Admin Only)
└── /queue/* (All Users)
```

### 3.2 Pluggable & Abstracted Model Layer
To future-proof the codebase, model interaction is decoupled via an Abstract Factory design. The system ships with support for a modern **YOLO family segmentation architecture** (e.g., YOLO11-seg), but any custom model can be added by implementing the base abstract interface:

```python
from abc import ABC, abstractmethod
from typing import Any, List, Dict

class AbstractSegmentationModel(ABC):
    @abstractmethod
    def load_weights(self, checkpoint_path: str) -> None:
        """Loads model parameters into memory/GPU."""
        pass

    @abstractmethod
    def run_inference(self, image_bytes: bytes) -> List[Dict[str, Any]]:
        """Extracts class labels, bounding boxes, and uncertainty confidence metrics."""
        pass

    @abstractmethod
    def train_step(self, dataset_path: str, output_path: str, config: Dict[str, Any]) -> Float:
        """Executes a model fine-tuning run on newly annotated data."""
        pass
```

### 3.3 Abstracted Storage Provider (Local File System First)
To keep the initial implementation straightforward while keeping cloud scalability intact, all I/O operations go through an 
abstract StorageProvider. At installation, variables in the .env file target a local backend directory path, but this interface 
can easily be extended to support Network Attached Storage (NAS) or an S3 bucket without altering downstream code.

``` python
class StorageProvider(ABC):
    @abstractmethod
    def get_image(self, file_id: str) -> bytes: pass
    @abstractmethod
    def save_image(self, file_id: str, data: bytes) -> str: pass
```
### The Active Learning Lifecycle
1. **Uncertainty Query Phase:** The backend processes the unlabeled image pool through a lightweight inference check (e.g., scoring objectness/class confidence entropy from a trained detector or tracking boundary variance).
2. **Dynamic Work Allocation:** When an operator clicks `Next Image`, the backend fetches the top candidate determined by the active learning strategy, flags its status as `In-Progress` with an automatic TTL lease to prevent multi-user collisions, and delivers it to the frontend.
3. **Interactive Assisted Labeling:**
   * The user clicks an object or draws a rough box.
   * Coordinate markers are dispatched instantly to a dedicated `/api/v1/inference/sam-predict` endpoint.
   * **SAM 3.1** processes the prompt array using a cached image embedding, returning a precise array of vertex paths.
   * The client renders these instantly into editable vector layers.
4. **Ingestion & Model Adaptation:** The completed annotation is submitted via JSON (structured as COCO format polygons). When the verified annotation storage hits a defined batch size threshold (e.g., every 100 new verified frames), an asynchronous background task is automatically scheduled to fine-tune the model parameters.

---

## 4. Key Architectural & Performance Guardrails

### 1. In-Memory Image Handling & Embedding Caching
To prevent crippling disk I/O bottlenecks:
* Images are loaded into RAM/VRAM as byte arrays using OpenCV or PIL.
* When an image is assigned to a user, its heavy **SAM Image Embedding** must be computed *once* and cached in memory or fast temporary storage. Subsequent point clicks or bounding box adjustments pass a lightweight token representing the cached embedding, keeping response times under **50ms**.

### 2. Multi-User Queue Locking (Anti-Collisions)
To ensure multiple annotators never process the same image simultaneously:
* The backend employs atomic transactions (`SELECT FOR UPDATE SKIP LOCKED` or Redis locks) to capture the next best frame for the requesting user.
* Every checked-out image has an expiration window (e.g., 10 minutes). If no annotation is submitted within the window, the lock is released back to the general pool.

### 3. GPU Workload & VRAM Separation
To prevent fatal `CUDA Out of Memory` crashes on shared host infrastructure:
* **Inference Pipeline:** Allocated a fixed, immutable slice of VRAM or handled by a lightweight dedicated worker process.
* **Training Pipeline:** Configured with strict process limits and execution locks. Training processes are isolated using Python context managers or explicit worker resource allocation so they never compete for the same physical VRAM pages during active, real-time user inference sessions.

---

## 5. Next Steps & Open Architectural Clarifications

To move this document from high-level design specification to code execution, please provide clarity on the following elements:

1. **User Identity & Auth:** Do you require robust, multi-tenant role-based authentication (e.g., Admins vs. Annotators), or will this run within an internal, trusted local network with simple name identifiers?
2. **Current Model Infrastructure:** Do you have an existing downstream detection/segmentation model (like a YOLOv8-seg, YOLOv11-seg, or Mask R-CNN) that you intend to retrain inside this active learning loop, or are we designing the retraining module from absolute scratch?
3. **Storage Environment:** Where do raw source images reside? (Local system directories, network-attached storage/NFS, or an S3/MinIO-compatible object storage server?)