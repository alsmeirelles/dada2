# Software Requirements & Architecture Specification: General-Purpose Object-Level DADA Active Learning Engine

## 1. Theoretical Background: What is DADA and How It Works

### 1.1 The Pathology of Pure Uncertainty Sampling

In standard pool-based Active Learning (AL), an acquisition function evaluates an unlabeled pool of samples $U$ using a model $M$ and selects the top $Q$ samples with the highest prediction uncertainty (e.g., via Maximum Entropy, BALD, or Variation Ratios computed over Monte Carlo Dropout passes or Deep Ensembles).

However, in large computer vision datasets (originally observed by Meirelles et al., 2022 & 2023 in gigapixel histopathology whole-slide images), **pure uncertainty sampling suffers from severe visual and spatial redundancy**. Because the model struggles with specific morphological or visual patterns, the top $Q$ most uncertain samples in any given iteration tend to share nearly identical visual features. Annotating a batch of near-duplicate uncertain samples yields diminishing returns for model generalization while wasting human annotation budget. Conversely, pure geometric diversity methods (such as CoreSet) select visually distinct samples that the model may already classify with high confidence.

### 1.2 The Core DADA Algorithm

**Diversity-Aware Data Acquisition (DADA)** resolves this trade-off by coupling feature-space clustering (information density/diversity) with uncertainty-weighted quota allocation. In each AL acquisition step, DADA executes five core stages:

1. **Dynamic Subpooling ($S_U \subset U$):**
   Evaluating deep uncertainty across hundreds of thousands of unlabeled candidates is computationally prohibitive. DADA samples a smaller dynamic subpool $S_U$ (e.g., $2,000$ to $10,000$ items) from the master pool $U$. This subpool is replaced/regenerated every $\alpha$ acquisition steps (typically $\alpha = 2$), reducing acquisition compute time while maintaining spatial and visual coverage.

2. **Joint Uncertainty & Deep Feature Extraction:**
   As the model evaluates items $x \in S_U$ to compute scalar uncertainty scores $U(x)$, DADA simultaneously extracts high-level semantic feature vectors $\mathbf{z} \in \mathbb{R}^D$ from the penultimate layer (last convolutional/neck layer) of the network.

3. **Unsupervised Dimensionality Reduction (PCA):**
   Because raw deep feature vectors $\mathbf{z}$ have high dimensionality ($D \in [512, 4608]$), Euclidean distance metrics degrade during clustering. DADA applies Principal Component Analysis (PCA) to project $\mathbf{z}$ into a compact orthogonal manifold $\mathbf{z}' \in \mathbb{R}^d$ (typically $d = 50$).

4. **Feature Space Clustering (`MiniBatchKMeans`):**
   The projected items in $S_U$ are partitioned into $K$ homogeneous visual clusters $\{C_1, C_2, \dots, C_K\}$ (typically $K \in [20, 80]$) using Mini-Batch $k$-means for fast runtime execution.

5. **Uncertainty-Weighted Cluster Quota Allocation:**
   Rather than sampling equally from each cluster, DADA weights each cluster's acquisition quota by its mean uncertainty $Z(k)$:

   $$
   Z(k) = \frac{1}{\vert C_k \vert} \sum_{x \in C_k} U(x)
   $$

   $$
   PR(k) = \frac{Z(k)}{\sum_{j=1}^K Z(j)}
   $$

   $$
   \text{acqSize}(k) = \operatorname{round}\left(PR(k) \times Q\right)
   $$

   Within each cluster $C_k$, candidates are sorted in descending order of their individual uncertainty $U(x)$, and the top $\text{acqSize}(k)$ items are acquired for human annotation.

### 1.3 Network Auto-Reduction (NAR) in Original DADA

To further accelerate the AL loop, Meirelles et al. (2023) introduced **Network Auto-Reduction (NAR)**. Inspired by EfficientNet compound scaling, NAR scales *down* the target CNN’s depth ($d = \alpha^{-\phi}$), width ($w = \beta^{-\phi}$), and input resolution ($r = \gamma^{-\phi}$) controlled by a single hyperparameter $\phi$. The lightweight reduced network acts as a proxy during the AL loop to train rapidly and select informative samples, which are then used to train the full-scale target architecture.

---

## 2. Summary of Adaptations for General-Purpose & Object-Level Vision

To generalize DADA from patch-level classification to an industry-grade, multi-task engine supporting **Image Classification, Object Detection, and Instance Segmentation** at the **individual object level** (supporting **YOLO11, YOLO12, and YOLO26** for detection/segmentation and configurable **`timm`** models defaulting to **`EfficientNet-B1`/`B5`** for classification), this specification mandates four architectural adaptations:

| Original DADA Component | Adaptation in This Specification | Engineering Rationale |
| :--- | :--- | :--- |
| **NAR Custom Model Pruning** ($\phi$ scaling on CNN blocks) | **Native Architecture Family Proxy Scaling** (Defaults: `efficientnet_b1` proxy / `efficientnet_b5` target for Classification; `yolo26n`/`s`, `yolo12n`/`s`, or `yolo11n`/`s` proxy for `l`/`x` target; user-configurable) | Eliminates writing custom graph-pruning code for every new architecture while preserving structural feature alignment. Keeps original resolution input size. |
| **MC Dropout ($F=20$) / Full Ensembles ($N=3$)** | **Classification:** Deep Ensemble ($N=3$ proxies) or Multi-View TTA ($T=5$ passes). **Detection/Segmentation:** Single-Pass Pre-NMS Proposal Cluster Variance (+ YOLO26 Dual-Head Disagreement) or 3-Pass TTA Jitter. | Avoids modifying model architectures to inject inference dropout and eliminates $20\times$ forward-pass bottlenecks on dense detectors. |
| **Single-Tier Image Subpool** ($S_U$) | **Two-Tier Dynamic Subpooling** (Image Subpool $S_{\text{img}}$ + Object Gatekeeper $S_{\text{obj}}$) + **Multi-Scale GPU `RoIAlign` Hooks** | Prevents memory explosions when $2,000$ images yield $>50,000$ candidate object boxes/masks; extracts L2-normalized per-object embeddings across `P3–P5` in milliseconds. |
| **Fully Labeled Patch Dataset** | **Partially Annotated Image (PAI) Schema & Region-Aware Training** | Because users only annotate selected uncertain objects, images contain unqueried objects. Mode 1 (Region-Aware Loss Masking) enforces exact zero background gradient on unqueried regions. |

---

## 3. System Architecture & Repository Layout

DADA shall be self-contained and conform to the [general specification](active_learning_requirements_specification.md). Its proposed implementation uses Python 3.10+, PyTorch 2.x, Ultralytics, `timm`, `scikit-learn`, and `pydantic` under the following modular structure:

```text
active_learning
    ├──dada_al/
        ├── config/
        │   └── schema.py                 # Pydantic configuration schemas
        │   └── config.yml                # YAML configuration file with DADAAlConfig configuration parameters
        ├── models/
        │   ├── base_adapter.py           # DADA internal model adapter interface
        │   ├── yolo_adapter.py           # Ultralytics YOLO (v11, v12, v26) Detection & Segmentation adapter
        │   └── timm_adapter.py           # PyTorch Image Models (timm) Classification adapter (EfficientNet-B1/B5 default)
        ├── uncertainty/
        │   ├── metrics.py                # Softmax BALD, Augmented Simplex BALD, IoU Dispersion, DFL & Mask Entropy
        │   ├── cls_extractor.py          # Classification Deep Ensemble (N=3) & Multi-View TTA (T=5) uncertainty/feature extractor
        │   ├── pre_nms_extractor.py      # Single-pass O2M proposal cluster + YOLO26 O2O Dual-Head hook & scorer
        │   └── tta_extractor.py          # 3-pass scale/flip TTA box/mask matcher & scorer
        ├── acquisition/
        │   ├── subpool_manager.py        # Two-tier dynamic subpooling (Image + Object gatekeeper)
        │   ├── feature_extractor.py      # FPN RoIAlign & penultimate layer embedding hooks
        │   └── dada_selector.py          # PCA + MiniBatchKMeans + proportional cluster quota logic
        ├── dataset/
        │   ├── pai_schema.py             # Partially Annotated Image (PAI) Extended COCO schema
        │   └── pai_trainer.py            # Mode 1 Region-Aware Loss Masking & Mode 2 Visual Neutralization fallback
        └── pipeline/
            └── al_loop.py                # Main Active Learning orchestrator
```

---

## 4. Detailed Module Specifications

### 4.1 Configuration & Data Structures (`config/schema.py`)

Implement strict `pydantic` configuration classes:

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Tuple

class TaskType(str, Enum):
    CLASSIFICATION = "classification"
    DETECTION = "detection"
    SEGMENTATION = "segmentation"

class UncertaintyMethod(str, Enum):
    # Detection & Segmentation methods
    PRE_NMS = "pre_nms"                  # Single-pass pre-NMS proposal cluster variance (+ Dual-Head in YOLO26)
    TTA_JITTER = "tta_jitter"            # 3-pass scale + horizontal flip TTA (Detection/Segmentation)
    # Classification methods
    DEEP_ENSEMBLE = "deep_ensemble"      # Option 1 (Default for Classification): N=3 independent proxy models
    TTA_MULTIVIEW = "tta_multiview"      # Option 2 (Classification): T=5 deterministic geometric views on 1 proxy model

class PAITrainingMode(str, Enum):
    MODE_1_LOSS_MASK = "mode_1_loss_mask"       # Default: Exact zero background gradient outside queried_rois
    MODE_2_VISUAL_MASK = "mode_2_visual_mask"   # Fallback: High-conf pseudo-labeling + pixel neutralization

class DADAAlConfig(BaseModel):
    task: TaskType
    target_model_name: Optional[str] = None  # Resolve from task defaults when omitted
    proxy_model_name: Optional[str] = None   # Resolve from task defaults when omitted
    uncertainty_method: Optional[UncertaintyMethod] = None  # Resolve from task defaults
    pai_training_mode: PAITrainingMode = PAITrainingMode.MODE_1_LOSS_MASK
    retain_helper_models: bool = False  # Retain proxy/helper checkpoints only when enabled
    
    # Classification Ensemble / TTA parameters
    cls_ensemble_size: int = 3           # N=3 independent proxy models for DEEP_ENSEMBLE
    cls_tta_views: int = 5               # T=5 geometric views for TTA_MULTIVIEW
    cls_entropy_blend: float = 0.20      # Blend weight of predictive entropy with BALD to prevent 0.0 on unanimous boundary cases
    
    # Subpooling parameters
    image_subpool_size: int = 2000
    subpool_renewal_interval: int = 2    # Alpha parameter in DADA
    max_object_candidates: int = 15000   # Tier-2 object gatekeeper ceiling
    candidate_conf_floor: float = 0.08   # Minimum confidence to enter object pool
    proposal_cluster_iou_thresh: float = 0.50 # tau_cluster for grouping pre-NMS proposals
    annotated_iou_dedup_thresh: float = 0.50
    
    # DADA Clustering & Quota parameters
    pca_components: int = 50
    num_clusters: int = 20               # K parameter in DADA
    acquisition_budget_q: int = Field(..., gt=0)  # Set from the API batch request
    
    # Uncertainty weighting hyperparameters (Convex combination summing to 1.0)
    cls_weight: float = 0.50             # Weight of classification uncertainty (0.40 for segmentation)
    loc_weight: float = 0.50             # Weight of localization uncertainty (0.30 for segmentation)
    mask_weight: float = 0.30            # Weight of mask uncertainty (used when task == SEGMENTATION)
    yolo26_dual_head_weight: float = 0.40 # Blend weight for O2O vs O2M head disagreement in YOLO26
    shrinkage_kappa: float = 2.0         # Effective sample size shrinkage constant for M=1 fallback
    mask_boundary_band_px: int = 3       # Morphological dilation/erosion kernel radius for boundary entropy
    roi_context_padding: float = 0.15    # 15% box expansion when defining queried_roi for annotators
```

Resolve omitted configuration values according to the request task before validation or execution:

| Task | Proxy model | Target model | Uncertainty method |
| --- | --- | --- | --- |
| Classification | `efficientnet_b1` | `efficientnet_b5` | `deep_ensemble` |
| Detection | `yolo26n.pt` | `yolo26x.pt` | `pre_nms` |
| Instance segmentation | `yolo26n-seg.pt` | `yolo26x-seg.pt` | `pre_nms` |

Explicit compatible settings override these defaults. Reject methods incompatible with the task: classification accepts `deep_ensemble` and `tta_multiview`; detection and segmentation accept `pre_nms` and `tta_jitter`. Validate model/task compatibility and reject unsupported combinations. `acquisition_budget_q` is populated from the API request's batch size for each run, not selected independently by DADA configuration.

#### Core Internal Data Transfer Object (`CandidateItem`)

Every evaluated unit (a whole image for classification, or a candidate bounding box/mask for detection and segmentation) must be standardized into a `CandidateItem`:

* `candidate_id`: `str` (UUID)
* `image_id`: `str`
* `bbox_xyxy`: `Optional[Tuple[float, float, float, float]]` (None for image classification)
* `mask_rle`: `Optional[dict]` (COCO RLE polygon/mask for segmentation)
* `pred_class_probs`: `np.ndarray` of shape `(C,)`
* `cls_uncertainty`: `float` (Strictly bounded in $[0, 1]$)
* `spatial_uncertainty`: `float` ($0.0$ for classification; strictly bounded in $[0, 1]$)
* `total_uncertainty`: `float` (Strictly bounded in $[0, 1]$)
* `feature_vector`: `np.ndarray` of shape `(D,)`

---

### 4.2 Model Adapters & Zero-Code NAR Proxy (`models/`)

DADA implements the [shared batch selection contract](active_learning_requirements_specification.md#batch-selection-interface). Its internal model adapters handle proxy and target training and candidate extraction; these operations are not part of the API-facing contract.

#### 1. `TimmClassificationAdapter` (`models/timm_adapter.py`)

Supports image classification architectures via `timm` (PyTorch Image Models) or custom PyTorch modules (`models/custom_model_name.py` providing both proxy and target definitions):

* **Configurable Defaults (`EfficientNet-B1` / `EfficientNet-B5`):**
  * By default, `proxy_model_name = "efficientnet_b1"` ($\phi = 1$) and `target_model_name = "efficientnet_b5"` ($\phi = 5$). Because NAR was originally derived from EfficientNet compound scaling equations ($d = \alpha^\phi, w = \beta^\phi, r = \gamma^\phi$), `EfficientNet-B1` provides a native $\approx 6.5\times$ FLOPS reduction while sharing the exact MBConv block topology of `EfficientNet-B5`.
  * Both `proxy_model_name` and `target_model_name` are user-configurable via `DADAAlConfig` (e.g., allowing users to switch to `convnext_tiny` / `convnext_base` or `resnet18` / `resnet50`).
* **PyTorch Forward Hooks for Feature Extraction:**
  * Register a forward hook on the global average pooled output of the penultimate layer (`model.global_pool` in `timm`, immediately after the final convolutional head `conv_head` and prior to the linear `classifier`). For `EfficientNet-B1`, this yields a vector $\mathbf{z}^{(n)} \in \mathbb{R}^{1280}$ per forward pass.
  * Apply unit-sphere $L_2$ normalization to each extracted vector:
    $$
    \hat{\mathbf{z}}^{(n)}(x) = \frac{\mathbf{z}^{(n)}(x)}{\Vert \mathbf{z}^{(n)}(x) \Vert_2 + \epsilon}
    $$
  * **Feature Aggregation Across Ensemble / TTA Passes:**
    * When using **Option 1 (`DEEP_ENSEMBLE`, $N=3$ independent proxy models)**: Because each independently initialized model learns a distinct permutation of the latent feature space, concatenate the $N$ $L_2$-normalized feature vectors and normalize the joint vector (matching Meirelles et al., 2022). Try to allocate the $N$ models concurrently and train in parallel. If the hardware can't hold them at the same time (OOM exceptions), train each sequentially:
      $$
      \mathbf{z}(x) = \frac{1}{\sqrt{N}} \operatorname{Concat}\left( \hat{\mathbf{z}}^{(1)}(x), \dots, \hat{\mathbf{z}}^{(N)}(x) \right) \in \mathbb{R}^{N \cdot D_{\text{backbone}}} \quad (\mathbb{R}^{3840} \text{ for } N=3 \text{ EfficientNet-B1})
      $$
    * When using **Option 2 (`TTA_MULTIVIEW`, $T=5$ views on $1$ proxy model)**: Because all $T$ views share the exact same model weights and aligned feature channels, compute the mean of the $T$ vectors and $L_2$-normalize:
      $$
      \mathbf{z}(x) = \frac{\sum_{t=1}^T \hat{\mathbf{z}}^{(t)}(x)}{\left\Vert \sum_{t=1}^T \hat{\mathbf{z}}^{(t)}(x) \right\Vert_2 + \epsilon} \in \mathbb{R}^{D_{\text{backbone}}} \quad (\mathbb{R}^{1280} \text{ for EfficientNet-B1})
      $$

#### 2. `YoloAdapter` (`models/yolo_adapter.py`)

Strictly supports **YOLO11 or later** (**YOLO11**, **YOLO12**, and **YOLO26**) for both Object Detection and Instance Segmentation (legacy YOLOv8/v9 versions are not supported):

* **Architectural Differences Handled by Adapter:**
  * **YOLO26:** Features a **Dual-Head Architecture** consisting of a dense **One-to-Many (O2M)** head ($8400$ grid anchors) and a sparse **One-to-One (O2O)** head ($300$ direct predictions for NMS-free inference), **DFL-Free continuous box regression**, **ProgLoss** (Progressive Loss Balancing), **STAL** (Small-Target-Aware Label Assignment), and the **MuSGD** optimizer.
  * **YOLO12:** Features an attention-centric backbone/neck with **R-ELAN** (Residual Efficient Layer Aggregation Networks with block-level scaling) and **Area Attention** ($l=4$ partitioned FlashAttention), alongside a single One-to-Many head with $16$-bin **Distribution Focal Loss (DFL)**.
  * **YOLO11:** Features `C3k2` + `SPPF` + `C2PSA` neck/backbone blocks and a single One-to-Many head with $16$-bin **DFL**.
* **Proxy Selection:** Pairs the configured target architecture with its corresponding Nano (`n`) or Small (`s`) variant (`yolo26n.pt` for `yolo26x.pt`, `yolo12n.pt` for `yolo12l.pt`, `yolo11n.pt` for `yolo11x.pt`), or allows user-configured cross-version proxies (e.g., `yolo26n.pt` proxy for `yolo12x.pt` target).
* **Multi-Scale PyTorch Forward Hooks for Feature Extraction:**
  * Register forward hooks on the three multi-scale neck feature maps feeding into the `Detect` or `Segment` head (in YOLO26 and YOLO11, these are the `C3k2` neck outputs at layer indices `16`, `19`, and `22`, corresponding to `P3` stride-8, `P4` stride-16, and `P5` stride-32; in YOLO12, the corresponding `R-ELAN` neck outputs).
  * Given $M$ candidate bounding boxes on an image, execute `torchvision.ops.roi_align(features, boxes, output_size=(1, 1), spatial_scale=...)` across **all three FPN levels (`P3`, `P4`, `P5`) simultaneously** and concatenate the three pooled vectors:
    $$
    \mathbf{z}_{\text{raw}}(o_j) = \operatorname{Concat}\left( \operatorname{RoIAlign}_{1\times 1}(P_3, b_j), \, \operatorname{RoIAlign}_{1\times 1}(P_4, b_j), \, \operatorname{RoIAlign}_{1\times 1}(P_5, b_j) \right)
    $$
  * **Mandatory L2 Normalization:** Apply unit-sphere L2 normalization on the GPU:
    $$
    \mathbf{z}(o_j) = \frac{\mathbf{z}_{\text{raw}}(o_j)}{\Vert \mathbf{z}_{\text{raw}}(o_j) \Vert_2 + \epsilon}
    $$
    This guarantees scale-invariant fixed-dimension embeddings and prevents high-magnitude YOLO12 Area Attention / R-ELAN outlier channels from dominating PCA variance.

---

### 4.3 Fast Uncertainty Engine (`uncertainty/`)

To guarantee rapid, mathematically valid uncertainty scores bounded strictly in $[0, 1]$ without modifying network architectures to inject inference-time MC-Dropout, implement the following calculators:

#### 1. Image Classification Uncertainty Extractor (`cls_extractor.py`)

Supports both **Option 1 (`DEEP_ENSEMBLE`)** and **Option 2 (`TTA_MULTIVIEW`)** selectable via `config.uncertainty_method`:

* **Option 1: Deep Ensemble (`DEEP_ENSEMBLE`, Default for Classification):**
  * Train $N = \text{cls\_ensemble\_size}$ (default $N = 3$) independent instances of `proxy_model_name` (`efficientnet_b1`) using distinct random seeds (`seed = 1..N`) for weight initialization and mini-batch shuffling.
  * During acquisition inference on $S_{\text{img}}$, evaluate each image $x$ across all $N$ proxy models to obtain $N$ categorical Softmax probability vectors $\mathbf{p}^{(1)}, \dots, \mathbf{p}^{(N)} \in \Delta^{C-1}$.
* **Option 2: Multi-View TTA Ensemble (`TTA_MULTIVIEW`):**
  * Train $1$ instance of `proxy_model_name` (`efficientnet_b1`).
  * During acquisition inference on $S_{\text{img}}$, evaluate each image $x$ across $T = \text{cls\_tta\_views}$ (default $T = 5$) deterministic geometric transformations:
    1. Original identity view $x$.
    2. Horizontally flipped view $\operatorname{HFlip}(x)$.
    3. Center zoom crop at $0.90\times$ scale resized to input resolution.
    4. Upper-left crop at $0.90\times$ scale resized to input resolution.
    5. Lower-right crop at $0.90\times$ scale resized to input resolution.
  * Collect the $T$ Softmax probability vectors $\mathbf{p}^{(1)}, \dots, \mathbf{p}^{(T)} \in \Delta^{C-1}$.
* **Classification Uncertainty Formula (Normalized Softmax BALD + Entropy Blend):**
  Let $M_{\text{passes}}$ be $N$ (for `DEEP_ENSEMBLE`) or $T$ (for `TTA_MULTIVIEW`), and let $\bar{\mathbf{p}} = \frac{1}{M_{\text{passes}}} \sum_{m=1}^{M_{\text{passes}}} \mathbf{p}^{(m)}$ be the mean predictive distribution. Define normalized categorical Shannon entropy:
  $$
  H_{\text{cls}}(\mathbf{p}) = -\frac{1}{\log C} \sum_{c=1}^{C} p_c \log(p_c) \in [0, 1]
  $$
  Compute normalized Softmax BALD (Mutual Information):
  $$
  U_{\text{BALD}}(x) = H_{\text{cls}}(\bar{\mathbf{p}}) - \frac{1}{M_{\text{passes}}} \sum_{m=1}^{M_{\text{passes}}} H_{\text{cls}}\left(\mathbf{p}^{(m)}\right) \in [0, 1]
  $$
  Blend with total predictive entropy using $\beta_{\text{ent}} = \text{cls\_entropy\_blend}$ ($0.20$) so ambiguous boundary samples where passes agree on a $50/50$ split still receive a non-zero uncertainty score:
  $$
  U_{\text{total}}(x) = U_{\text{cls}}(x) = (1 - \beta_{\text{ent}}) \, U_{\text{BALD}}(x) + \beta_{\text{ent}} \, H_{\text{cls}}(\bar{\mathbf{p}}) \in [0, 1]
  $$

#### 2. Single-Pass Pre-NMS Proposal Cluster & Dual-Head Extractor (`pre_nms_extractor.py`)

* **Hook Mechanism (Supporting Single-Head YOLO11/12 & Dual-Head YOLO26):**
  * Attach a forward hook to the `Detect` / `Segment` head during inference.
  * **Crucial for YOLO26:** Even though YOLO26 defaults to end-to-end NMS-free inference (`nms=False`) using only its One-to-One ($H_{\text{O2O}}$) head, both $H_{\text{O2M}}$ and $H_{\text{O2O}}$ are present and trained in every checkpoint. The hook **must intercept both**:
    1. The dense **One-to-Many ($H_{\text{O2M}}$)** raw tensor prior to NMS (shape: `[batch, 4 + C (+ 32 mask_protos), 8400]`).
    2. In YOLO26, the sparse **One-to-One ($H_{\text{O2O}}$)** decoded tensor (shape: `[batch, 300, 6 (+ 32 mask_protos)]`).
    3. In YOLO11 and YOLO12, the pre-softmax **16-bin DFL** regression tensor (shape: `[batch, 64, 8400]`).
* **Proposal Clustering:**
  1. Obtain the $M_{\text{obj}}$ surviving candidate objects per image with confidence $\ge \text{candidate\_conf\_floor}$ (`0.08`) by running standard NMS on $H_{\text{O2M}}$ (or taking the union with $H_{\text{O2O}}$ survivors in YOLO26).
  2. For each surviving object $o_j$ with reference box $b_j^*$ and top class $c^*$, compute the GPU IoU between $b_j^*$ and all pre-NMS anchor boxes in $H_{\text{O2M}}$ whose max class score exceeds `0.05`.
  3. Collect the local cluster of $K_j$ pre-NMS proposals $\{(b_m, \mathbf{p}_m)\}_{m=1}^{K_j}$ from $H_{\text{O2M}}$ that overlap with $b_j^*$ at $\text{IoU}(b_m, b_j^*) \ge \tau_{\text{cluster}}$ ($\tau_{\text{cluster}} = 0.50$).
  4. Compute normalized confidence weights across the $K_j$ proposals:
     $$
     s_m = \max_{c \in \{1..C\}} p_{m,c}, \qquad w_m = \frac{s_m}{\sum_{l=1}^{K_j} s_l}
     $$
  5. Compute the **Effective Sample Size Shrinkage Factor** $\gamma(K_j)$ to smoothly handle isolated detections where $K_j = 1$ (where empirical cluster variance would falsely collapse to $0$):
     $$
     \gamma(K_j) = \frac{K_j - 1}{K_j + \kappa} \quad (\text{with } \kappa = \text{shrinkage\_kappa} = 2.0)
     $$

* **Mathematical Formulations over Proposal Cluster $K_j$:**

  ##### A. Classification Uncertainty ($U_{\text{cls}}$) via Formulation B (Augmented Simplex Normalization)

  Because YOLO11/12/26 heads output $C$ independent Sigmoid probabilities $p_{m,c} \in (0, 1)$ where $\sum_{c=1}^C p_{m,c} \neq 1$, raw multi-class entropy is invalid. Map each proposal $m \in \{1, \dots, K_j\}$ onto the $(C+1)$-dimensional categorical probability simplex $\Delta^C$:

  1. Define explicit background probability for proposal $m$:
     $$
     \tilde{p}_{m, 0} = 1 - \max_{c \in \{1..C\}} p_{m, c}, \qquad \tilde{p}_{m, c} = p_{m, c} \text{ for } c \in \{1, \dots, C\}
     $$
  2. Normalize onto the simplex $\Delta^C$:
     $$
     \hat{p}_{m, c} = \frac{\tilde{p}_{m, c}}{\sum_{l=0}^{C} \tilde{p}_{m, l}} \quad \text{for } c \in \{0, \dots, C\}
     $$
  3. Compute normalized categorical Shannon entropy $H_{\text{norm}}(\hat{\mathbf{p}}) = -\frac{1}{\log(C+1)} \sum_{c=0}^{C} \hat{p}_c \log(\hat{p}_c) \in [0, 1]$ and mean distribution $\bar{\mathbf{p}} = \frac{1}{K_j} \sum_{m=1}^{K_j} \hat{\mathbf{p}}_m$.
  4. **One-to-Many Cluster BALD with $K_j=1$ Shrinkage Fallback:**
     $$
     U_{\text{O2M-cls}}(o_j) = \gamma(K_j) \left[ H_{\text{norm}}(\bar{\mathbf{p}}) - \frac{1}{K_j} \sum_{m=1}^{K_j} H_{\text{norm}}(\hat{\mathbf{p}}_m) \right] + \left(1 - \gamma(K_j)\right) H_{\text{norm}}(\hat{\mathbf{p}}_1) \in [0, 1]
     $$
  5. **YOLO26 Dual-Head Classification Disagreement:**
     In YOLO26, match $b_j^*$ to the highest-overlapping prediction in the One-to-One head $H_{\text{O2O}}$. Project the matched O2O prediction onto the simplex to obtain $\hat{\mathbf{p}}_{\text{O2O}}$ (if no O2O prediction overlaps at $\text{IoU} \ge 0.30$, set $\hat{\mathbf{p}}_{\text{O2O}} = [1, 0, \dots, 0]^\top$, representing pure background). Compute the normalized Jensen-Shannon Divergence:
     $$
     U_{\text{dual-cls}}(o_j) = H_{\text{norm}}\left(\frac{\bar{\mathbf{p}} + \hat{\mathbf{p}}_{\text{O2O}}}{2}\right) - \frac{H_{\text{norm}}(\bar{\mathbf{p}}) + H_{\text{norm}}(\hat{\mathbf{p}}_{\text{O2O}})}{2} \in [0, 1]
     $$
     * **Final Classification Uncertainty:**
       * For **YOLO26**: $U_{\text{cls}}(o_j) = (1 - \alpha_{\text{dual}}) \, U_{\text{O2M-cls}}(o_j) + \alpha_{\text{dual}} \, U_{\text{dual-cls}}(o_j)$ where $\alpha_{\text{dual}} = 0.40$.
       * For **YOLO11 / YOLO12**: $U_{\text{cls}}(o_j) = U_{\text{O2M-cls}}(o_j)$.

  ##### B. Detection Localization Uncertainty ($U_{\text{loc}}$) via Scale-Invariant IoU Dispersion

  1. **Single-Proposal Fallback Term $U_{\text{loc-prior}}(o_j)$:**
     * In **YOLO11 / YOLO12** (which have 16-bin DFL distributions $q_{1,e} \in \Delta^{15}$ per edge $e \in \{l, t, r, b\}$), use the exact normalized DFL edge entropy:
       $$
       U_{\text{loc-prior}}(o_j) = \frac{1}{4 \log(16)} \sum_{e \in \{l, t, r, b\}} \left( -\sum_{k=0}^{15} q_{1, e, k} \log q_{1, e, k} \right) \in [0, 1]
       $$
     * In **YOLO26** (which is DFL-free), use the complement of the primary confidence score: $U_{\text{loc-prior}}(o_j) = 1 - s_1 \in [0, 1]$.
  2. **One-to-Many Confidence-Weighted IoU Dispersion:**
     Rescaled by $(1 - \tau_{\text{cluster}})$ so dispersion spans $[0, 1]$:
     $$
     U_{\text{O2M-loc}}(o_j) = \gamma(K_j) \left( \frac{1 - \sum_{m=1}^{K_j} w_m \, \text{IoU}(b_m, b_j^*)}{1 - \tau_{\text{cluster}}} \right) + \left(1 - \gamma(K_j)\right) U_{\text{loc-prior}}(o_j) \in [0, 1]
     $$
  3. **YOLO26 Dual-Head Spatial Disagreement:**
     Measure the IoU discrepancy between the One-to-Many reference box $b_j^*$ and the matched One-to-One head box $b_{\text{O2O}}$ ($\text{IoU} = 0$ if unmatched):
     $$
     U_{\text{dual-loc}}(o_j) = 1 - \text{IoU}\left(b_j^*, \, b_{\text{O2O}}\right) \in [0, 1]
     $$
     * **Final Localization Uncertainty:**
       * For **YOLO26**: $U_{\text{loc}}(o_j) = (1 - \alpha_{\text{dual}}) \, U_{\text{O2M-loc}}(o_j) + \alpha_{\text{dual}} \, U_{\text{dual-loc}}(o_j)$.
       * For **YOLO11 / YOLO12**: $U_{\text{loc}}(o_j) = U_{\text{O2M-loc}}(o_j)$.

  ##### C. Instance Segmentation Uncertainty ($U_{\text{seg}}$)

  1. **Morphological Boundary-Band Binary Entropy ($U_{\text{seg-bound}}$):**
     Decode the surviving object's probability mask $M_j \in (0, 1)^{H_p \times W_p}$ and binarized mask $\hat{M}_j = \mathbb{I}(M_j > 0.5)$. Compute the morphological boundary band $B(\hat{M}_j) = \operatorname{Dilate}(\hat{M}_j, r) \setminus \operatorname{Erode}(\hat{M}_j, r)$ with radius $r = \text{mask\_boundary\_band\_px}$ (if $\operatorname{Erode}(\hat{M}_j, r)$ is empty for very small objects, set $B(\hat{M}_j) = \operatorname{Dilate}(\hat{M}_j, r)$). Calculate mean binary entropy in base 2 over pixels $i \in B(\hat{M}_j)$:
     $$
     U_{\text{seg-bound}}(o_j) = -\frac{1}{|B(\hat{M}_j)|} \sum_{i \in B(\hat{M}_j)} \left[ p_i \log_2 p_i + (1 - p_i) \log_2(1 - p_i) \right] \in [0, 1]
     $$
  2. **Pre-NMS Prototype Coefficient Spherical Variance ($U_{\text{seg-coeff}}$):**
     For the $K_j$ proposals in $H_{\text{O2M}}$, L2-normalize their 32-dimensional mask coefficient vectors $\hat{\mathbf{c}}_m = \frac{\mathbf{c}_m}{\|\mathbf{c}_m\|_2 + \epsilon}$ and compute spherical dispersion without decoding extra spatial masks:
     $$
     U_{\text{seg-coeff}}(o_j) = 1 - \left\| \sum_{m=1}^{K_j} w_m \hat{\mathbf{c}}_m \right\|_2 \in [0, 1]
     $$
  3. **Combined Mask Uncertainty:**
     $$
     U_{\text{mask}}(o_j) = 0.5 \, U_{\text{seg-bound}}(o_j) + 0.5 \, U_{\text{seg-coeff}}(o_j) \in [0, 1]
     $$

  ##### D. Unified Bounded Total Object Uncertainty ($U_{\text{total}} \in [0, 1]$)

  * **For Object Detection:**
    $$
    U_{\text{total}}(o_j) = w_{\text{cls}} \, U_{\text{cls}}(o_j) + w_{\text{loc}} \, U_{\text{loc}}(o_j) \quad (\text{where } w_{\text{cls}} + w_{\text{loc}} = 1.0)
    $$
  * **For Instance Segmentation:**
    $$
    U_{\text{total}}(o_j) = w_{\text{cls}} \, U_{\text{cls}}(o_j) + w_{\text{loc}} \, U_{\text{loc}}(o_j) + w_{\text{mask}} \, U_{\text{mask}}(o_j) \quad (\text{where } w_{\text{cls}} + w_{\text{loc}} + w_{\text{mask}} = 1.0)
    $$

#### 3. Three-Pass TTA Jitter Extractor for Detection & Segmentation (`tta_extractor.py`)

* Alternative for detection/segmentation models when `uncertainty_method == UncertaintyMethod.TTA_JITTER`:
  * Pass 1: Original image $I$.
  * Pass 2: Horizontally flipped image $\operatorname{Flip}(I)$ (invert boxes/masks back to original coordinate space).
  * Pass 3: Rescaled image $\operatorname{Scale}_{0.85}(I)$ (rescale boxes/masks back to original coordinate space).
* Match object detections across the $T=3$ passes using Hungarian bipartite matching ($\text{IoU} \ge 0.5$). If a candidate is missing in pass $t$, assign it the pure background simplex vector $\hat{\mathbf{p}}_t = [1, 0, \dots, 0]^\top$ and $\text{IoU} = 0$ with present passes.
* Compute $U_{\text{cls}}(o_j)$ using **Formulation B (Augmented Simplex BALD)** across the 3 passes, and $U_{\text{loc}}(o_j)$ using **Pairwise IoU Dispersion**:
  $$
  U_{\text{loc-TTA}}(o_j) = 1 - \frac{1}{\binom{3}{2}} \sum_{1 \le t_1 < t_2 \le 3} \text{IoU}\left(g_{t_1}^{-1}(b^{(t_1)}), \, g_{t_2}^{-1}(b^{(t_2)})\right) \in [0, 1]
  $$

---

### 4.4 Two-Tier Dynamic Subpooling & DADA Selector (`acquisition/`)

#### 1. Two-Tier Subpool Manager (`subpool_manager.py`)

* **Tier 1 (Image Subpool $S_{\text{img}}$):**
  * Maintain state of the master image pool $U$ (which includes `UNLABELED` and `PARTIALLY_LABELED` images, excluding `EXHAUSTIVELY_LABELED` images).
  * Sample `image_subpool_size` images uniformly at random. Cache and reuse $S_{\text{img}}$ for `subpool_renewal_interval` ($\alpha = 2$) AL iterations before resampling.
* **Tier 2 (Object Candidate Gatekeeper $S_{\text{obj}}$):**
  * For `TaskType.CLASSIFICATION`, each image in $S_{\text{img}}$ produces a single image-level `CandidateItem` ($|S_{\text{obj}}| = |S_{\text{img}}|$).
  * For `TaskType.DETECTION` and `TaskType.SEGMENTATION`, run proxy inference on $S_{\text{img}}$ to collect raw object-level `CandidateItem` instances.
  * **Deduplication against Existing Annotations:** For any `PARTIALLY_LABELED` image, load its existing human-verified annotations (both positive boxes and verified hard-negative ROIs). Discard any candidate $o_j$ that overlaps with an existing annotation or queried ROI at $\text{IoU} \ge \text{annotated\_iou\_dedup\_thresh}$ ($0.50$).
  * **Candidate Ceiling Pre-Filter:** If total surviving candidates $\vert S_{\text{obj}} \vert > \text{max\_object\_candidates}$ ($15,000$), sort candidates by $U_{\text{total}}$ and retain the top `max_object_candidates` to guarantee that PCA and clustering execute in $< 5$ seconds.

#### 2. DADA Clustering & Quota Selector (`dada_selector.py`)

Implement Algorithm 1 from Meirelles et al. (2022) adapted to `CandidateItem` objects:

1. Stack L2-normalized feature vectors $\mathbf{Z} \in \mathbb{R}^{|S_{\text{obj}}| \times D}$.
2. Apply `sklearn.decomposition.PCA(n_components=min(config.pca_components, len(S_obj), D))` to obtain reduced matrix $\mathbf{Z}'$.
3. Apply `sklearn.cluster.MiniBatchKMeans(n_clusters=config.num_clusters, batch_size=1024)` on $\mathbf{Z}'$ to assign cluster labels $c_j \in \{0, \dots, K-1\}$.
4. For each cluster $k \in \{0, \dots, K-1\}$:
   * Calculate mean cluster uncertainty: $Z(k) = \frac{1}{\vert C_k \vert} \sum_{o_j \in C_k} U_{\text{total}}(o_j)$.
5. Compute cluster proportion $PR(k) = \frac{Z(k)}{\sum_{m=0}^{K-1} Z(m)}$.
6. Allocate integer quotas using the Largest Remainder Method, targeting $Q = \text{acquisition\_budget\_q}$ from the API request, subject to available eligible candidates. [P7-09](../phases/phase_7.md#p7-09--dada-selection-edge-cases) governs edge cases and quota redistribution.
7. Within each cluster $C_k$, sort candidates descending by $U_{\text{total}}(o_j)$ and select the top $\text{acqSize}(k)$ items.
8. **Query ROI Generation (Detection & Segmentation):** For each selected object with bounding box $[x_1, y_1, x_2, y_2]$, expand the box by `roi_context_padding` ($15\%$) clipped to image dimensions to create the `queried_roi` window presented to human annotators.

---

### 4.5 Shared annotation and training requirements

DADA generates query regions as described in section 4.4. The API owns annotation, consensus and the labeled pool. DADA consumes the resulting snapshots and handles partial-label training internally.

The caller supplies training and unlabeled-pool manifests with references to accessible images and any existing target geometry. DADA opens and reads the referenced images and regions as needed; it does not copy, move, or return image files. It returns a selection manifest in the same format as the received pool manifest, retaining the original image and object references and identifying selected images or, for object tasks, selected objects and proposed geometry. Where newly proposed objects have no incoming object reference, identify them using the input image reference and their proposed geometry; do not invent or replace source references. The API validates the result, dispatches annotation jobs, and manages the annotation flow. The precise common manifest schema and object identity representation remain subject to P7-08.

---

### 4.6 Partially Annotated Image (PAI) Dataset & Training Pipeline (`dataset/`)

When annotators only label selected objects in detection or segmentation tasks, the resulting images are **Partially Annotated Images (PAIs)**: they contain verified objects inside `queried_rois`, verified background/hard-negatives inside dismissed `queried_rois`, and **unknown/unqueried pixels** everywhere else.

#### 1. Extended COCO-PAI JSON Schema (`pai_schema.py`)

The dataset state must be serialized in an extended COCO format that tracks spatial query history:

```json
{
  "images": [
    {
      "id": 1042,
      "file_name": "img_1042.jpg",
      "width": 1920,
      "height": 1080,
      "annotation_status": "PARTIALLY_LABELED",
      "queried_rois": [
        {
          "roi_id": "roi_991",
          "bbox_xyxy": [120.0, 340.0, 280.0, 510.0],
          "al_iteration": 3,
          "resolution": "CONFIRMED_OBJECT"
        },
        {
          "roi_id": "roi_992",
          "bbox_xyxy": [800.0, 100.0, 950.0, 260.0],
          "al_iteration": 4,
          "resolution": "EXPLICIT_HARD_NEGATIVE"
        }
      ]
    }
  ],
  "annotations": [
    {
      "id": 5001,
      "image_id": 1042,
      "roi_id": "roi_991",
      "category_id": 2,
      "bbox": [135.0, 355.0, 125.0, 135.0],
      "segmentation": [[...]],
      "origin": "AL_OBJECT_QUERY",
      "resolution_confidence": 0.94
    }
  ]
}
```

* **`resolution == "EXPLICIT_HARD_NEGATIVE"`:** Occurs when DADA flags a candidate object, presents the `queried_roi` to the annotator(s), and the annotators mark the region as containing no valid object (false positive). This region is a confirmed background zone.

#### 2. Background-Safe PAI Training Pipeline (`pai_trainer.py`)

Standard object detectors treat every anchor outside ground-truth boxes as negative background ($y=0$). Training naively on `PARTIALLY_LABELED` images penalizes the model when it detects real, unqueried objects outside `queried_rois`. Implement **two selectable training modes** with distinct guarantees:

##### Mode 1 (`MODE_1_LOSS_MASK` — Default & Primary): Region-Aware Loss Masking (`PAIYoloTrainer`)

* **Guarantee:** **Strictly enforces an exact $0.0$ negative background classification gradient on all unmatched anchors/queries falling outside `queried_rois`**, while keeping input images visually unmodified to preserve natural context and BatchNorm statistics.
* **Implementation:** Subclass `ultralytics.models.yolo.detect.DetectionTrainer` (and `SegmentationTrainer`):
  1. Pass the union of `queried_rois` per image into the data loader batch dictionary.
  2. In the loss computation—using the version-agnostic **`OneToManyDetectionLoss`** wrapper for single-head NMS architectures (**YOLO11** and **YOLO12**) and the dual-head **`ProgLoss` / `DualHeadDetectionLoss`** wrapper for **YOLO26**—compute a binary spatial validity weight $W_a \in \{0.0, 1.0\}$ for every anchor/query $a$:
     * $W_a = 1.0$ **if and only if**:
       1. `annotation_status == "EXHAUSTIVELY_LABELED"`, **OR**
       2. Anchor $a$ is matched as a **positive foreground sample** (via TAL in YOLO11/12 or STAL in YOLO26), **OR**
       3. Anchor $a$'s spatial center point $(c_x, c_y)$ falls inside at least one verified `queried_roi` box (`CONFIRMED_OBJECT` or `EXPLICIT_HARD_NEGATIVE`).
     * $W_a = 0.0$ for all unmatched anchors whose center $(c_x, c_y)$ lies in unqueried image regions.
  3. Multiply the negative/background Binary Cross-Entropy (BCE) classification loss term for anchor $a$ by $W_a$ before reduction across **both** the One-to-Many head ($\mathcal{L}_{\text{O2M}}$) and, in YOLO26, the One-to-One head ($\mathcal{L}_{\text{O2O}}$):
     $$
     \mathcal{L}_{\text{cls-bg}}(a) = W_a \cdot \sum_{c=1}^{C} \operatorname{BCE}\left(\sigma(z_{a,c}), \, 0\right)
     $$
     Because $W_a = 0.0$ outside `queried_rois`, $\frac{\partial \mathcal{L}_{\text{cls-bg}}(a)}{\partial z_{a,c}} \equiv 0.0$ identically. Positive matched anchors always receive full box, class, and DFL/mask loss weight ($1.0$).

##### Mode 2 (`MODE_2_VISUAL_MASK` — Optional Fallback for External Black-Box Trainers): Visual Neutralization + High-Confidence Pseudo-Labeling

* **Guarantee:** Designed for external or frozen training loops where the loss function cannot be overridden. **Note:** Mode 2 does *not* produce zero background gradient at the logit layer (because standard BCE still evaluates $y=0$ on masked pixels); instead, it satisfies the **Visual Feature Suppression & Pseudo-Label Protection Criterion**.
* **Implementation:** Before launching a training run, generate a temporary training view of all `PARTIALLY_LABELED` images:
  1. **High-Confidence Pseudo-Label Injection:** Run the current best model over `PARTIALLY_LABELED` images. Any prediction outside `queried_rois` with confidence $\ge 0.80$ is temporarily added to the image's positive ground-truth training labels ($y=1$) for the upcoming epoch cycle.
  2. **Unqueried Region Pixel Neutralization:** Construct a pixel validity mask $W_{\text{px}} \in \{0, 1\}^{H \times W}$ where $W_{\text{px}} = 1$ inside all `queried_rois` and inside injected high-confidence pseudo-label boxes. Everywhere else ($W_{\text{px}} = 0$), replace pixel values with the dataset mean RGB value `(114, 114, 114)` or a heavy Gaussian blur $(\sigma = 25)$ so unqueried foreground objects are visually erased before convolutional filters process the image.

---

## 5. End-to-End Active Learning Loop Orchestration (`pipeline/al_loop.py`)

The main orchestrator (`ActiveLearningOrchestrator.step()`) shall execute the following state machine per iteration $i$:

1. **Train Proxy Selector:** Train the lightweight proxy model (`proxy_model_name`, defaulting to `efficientnet_b1` for classification—training $N=3$ instances if `DEEP_ENSEMBLE` is selected, or $1$ instance if `TTA_MULTIVIEW` is selected—and `yolo26n.pt`, `yolo12n.pt`, or `yolo11n.pt` for detection/segmentation) on the current labeled dataset $L^i$ using `pai_trainer.py` for $E_{\text{proxy}}$ epochs.
2. **Tier-1 Subpool Sampling:** Query `SubpoolManager` to retrieve or renew the active image subpool $S_{\text{img}}^i \subset U^i$.
3. **Candidate & Feature Extraction:** Run the trained proxy model(s) over $S_{\text{img}}^i$ with forward hooks enabled (`cls_extractor` for classification; `pre_nms_extractor` or `tta_extractor` + multi-scale `roi_align` feature hook for detection/segmentation) to produce raw `CandidateItem` instances.
4. **Tier-2 Gatekeeper Filtering:** For detection and segmentation, filter out candidates overlapping already-queried ROIs ($\text{IoU} \ge 0.5$) and cap total candidates at `max_object_candidates`.
5. **DADA Selection:** Execute PCA dimensionality reduction, `MiniBatchKMeans` clustering, and proportional uncertainty quota allocation to select up to the requested $Q$ eligible items (images for classification; objects for detection/segmentation). Report a shortfall and reason if insufficient eligible candidates are available.
6. **Prepare selection:** Generate padded `queried_roi` coordinates for selected objects, or identify selected images for classification, preserving the input references.
7. **Return batch:** Return a selection manifest in the input pool manifest format to the API, including selected object geometry where applicable. The API dispatches annotation jobs and manages accepted results; DADA receives an updated training snapshot on a later request.
8. **Scheduled target-model evaluation:** At the user-selected evaluation frequency, train and evaluate the target architecture (`target_model_name`, defaulting to `efficientnet_b5` for classification or the user-configured YOLO11/12/26 target) using the supplied training and separate validation data, and report metrics with iteration and model provenance. Never report proxy performance as target-model evaluation. Cadence options and stopping rules follow [P7-03](../phases/phase_7.md#p7-03--iteration-stopping-and-recovery). Proxy/helper checkpoints are temporary and removed after operational or retry needs end unless `retain_helper_models` is explicitly enabled; target-model retention follows the applicable run policy.

---

## 6. Verification & Acceptance Criteria for the Coding Agent

1. **Unit Test — Classification Ensemble & TTA Extractor (`cls_extractor.py`):** Verify with `efficientnet_b1` that Option 1 (`DEEP_ENSEMBLE`, $N=3$) outputs L2-normalized concatenated features of shape `(B, 3840)` and Option 2 (`TTA_MULTIVIEW`, $T=5$) outputs L2-normalized mean features of shape `(B, 1280)`, with $U_{\text{cls}} \in [0.0, 1.0]$ and strictly positive uncertainty ($> 0.0$) on unanimous $50/50$ boundary predictions.
2. **Unit Test — YOLO11/12/26 Pre-NMS / Dual-Head Hook & RoIAlign Speed:** Verify on a batch of 16 images ($640 \times 640$) with `yolo26n.pt`, `yolo12n.pt`, and `yolo11n-seg.pt` that pre-NMS/dual-head uncertainty scoring and multi-scale GPU `roi_align` feature extraction complete in $< 50\text{ ms}$ per image on a single GPU without CPU-GPU tensor copy bottlenecks.
3. **Unit Test — Simplex & Dispersion Bounds:** Verify that `metrics.py` produces $U_{\text{cls}}, U_{\text{loc}}, U_{\text{mask}}, U_{\text{total}} \in [0.0, 1.0]$ across all edge cases, including when $K_j = 1$ (single surviving proposal) and when YOLO26's O2O head misses an object detected by the O2M head.
4. **Unit Test — Quota Conservation:** Verify that `dada_selector.py` returns $Q$ candidates when sufficient eligible candidates exist, and otherwise returns the available candidates with a shortfall reason; cover empty clusters, single-item clusters, and zero uncertainty in accordance with P7-09.
5. **Unit Test — Deduplication Gatekeeper:** Verify that if an object at `[100, 100, 200, 200]` is already recorded in `queried_rois` (either as a positive object or an explicit hard negative), any new candidate overlapping it with $\text{IoU} \ge 0.50$ is strictly excluded from selection in subsequent AL iterations.
6. **Integration Test — PAI Mode 1 Exact Zero Background Gradient (`MODE_1_LOSS_MASK`):** On a synthetic `PARTIALLY_LABELED` image containing 5 objects where only 1 object is inside `queried_rois`, attach a backward hook to the raw classification logit tensor (`pred_scores` in `OneToManyDetectionLoss` for YOLO11/12, and both O2M and O2O logit tensors in `ProgLoss` for YOLO26). Assert that for every unmatched anchor $a$ whose center $(c_x, c_y)$ lies outside `queried_rois`, the backpropagated gradient is exact zero: $\max_{(c_x, c_y) \notin \text{queried\_rois}} \left|\frac{\partial \mathcal{L}}{\partial z_{a,c}}\right| == 0.0$.
7. **Integration Test — PAI Mode 2 Visual Suppression & Pseudo-Label Protection (`MODE_2_VISUAL_MASK`):** On the same synthetic `PARTIALLY_LABELED` image, verify that (a) unqueried predictions with confidence $\ge 0.80$ are injected into the temporary positive ground-truth label tensor, and (b) all pixels outside the union of `queried_rois` and injected pseudo-label boxes equal `(114, 114, 114)` (or the configured Gaussian blur) prior to forward pass execution.