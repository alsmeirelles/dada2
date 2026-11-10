# Software Requirements & Architecture Specification: General-Purpose Object-Level DADA Active Learning Engine

## 1. Theoretical Background: What is DADA and How It Works

### 1.1 The Pathology of Pure Uncertainty Sampling
In standard pool-based Active Learning (AL), an acquisition function evaluates an unlabeled pool of samples $U$ using a model $M$ and selects the top $Q$ samples with the highest prediction uncertainty (e.g., via Maximum Entropy, BALD, or Variation Ratios computed over Monte Carlo Dropout passes or Deep Ensembles). 

However, in large computer vision datasets (originally observed by Meirelles et al., 2022 & 2023 in gigapixel histopathology whole-slide images), **pure uncertainty sampling suffers from severe visual and spatial redundancy**. Because the model struggles with specific morphological or visual patterns, the top $Q$ most uncertain samples in any given iteration tend to share nearly identical visual features. Annotating a batch of near-duplicate uncertain samples yields diminishing returns for model generalization while wasting human annotation budget. Conversely, pure geometric diversity methods (such as CoreSet) select visually distinct samples that the model may already classify with high confidence.

### 1.2 The Core DADA Algorithm
**Diversity-Aware Data Acquisition (DADA)** resolves this trade-off by coupling feature-space clustering (information density/diversity) with uncertainty-weighted quota allocation. In each AL acquisition step, DADA executes five core stages:

1. **Dynamic Subpooling ( $S_U \subset U$):**
   Evaluating deep uncertainty across hundreds of thousands of unlabeled candidates is computationally prohibitive. DADA samples a smaller dynamic subpool $S_U$ (e.g., $2,000$ to $10,000$ items) from the master pool $U$. This subpool is replaced/regenerated every $\alpha$ acquisition steps (typically $\alpha = 2$), reducing acquisition compute time while maintaining spatial and visual coverage.
2. **Joint Uncertainty & Deep Feature Extraction:**
   As the model evaluates items $x \in S_U$ to compute scalar uncertainty scores $U(x)$, DADA simultaneously extracts high-level semantic feature vectors $\mathbf{z} \in \mathbb{R}^D$ from the penultimate layer (last convolutional/neck layer) of the network.
3. **Unsupervised Dimensionality Reduction (PCA):**
   Because raw deep feature vectors $\mathbf{z}$ have high dimensionality ( $D \in [512, 4608]$), Euclidean distance metrics degrade during clustering. DADA applies Principal Component Analysis (PCA) to project $\mathbf{z}$ into a compact orthogonal manifold $\mathbf{z}' \in \mathbb{R}^d$ (typically $d = 50$).
4. **Feature Space Clustering (`MiniBatchKMeans`):**
   The projected items in $S_U$ are partitioned into $K$ homogeneous visual clusters $\{C_1, C_2, \dots, C_K\}$ (typically $K \in [20, 80]$) using Mini-Batch $k$-means for fast runtime execution.
5. **Uncertainty-Weighted Cluster Quota Allocation:**
   Rather than sampling equally from each cluster, DADA weights each cluster's acquisition quota by its mean uncertainty $Z(k)$:
   $$Z(k) = \frac{1}{|C_k|} \sum_{x \in C_k} U(x)$$
   $$PR(k) = \frac{Z(k)}{\sum_{j=1}^K Z(j)}$$
   $$\text{acqSize}(k) = \operatorname{round}\left(PR(k) \times Q\right)$$
   Within each cluster $C_k$, candidates are sorted in descending order of their individual uncertainty $U(x)$, and the top $\text{acqSize}(k)$ items are acquired for human annotation.

### 1.3 Network Auto-Reduction (NAR) in Original DADA
To further accelerate the AL loop, Meirelles et al. (2023) introduced **Network Auto-Reduction (NAR)**. Inspired by EfficientNet compound scaling, NAR scales *down* the target CNN’s depth ( $d = \alpha^{-\phi}$), width ( $w = \beta^{-\phi}$), and input resolution ( $r = \gamma^{-\phi}$) controlled by a single hyperparameter $\phi$. The lightweight reduced network acts as a proxy during the AL loop to train rapidly and select informative samples, which are then used to train the full-scale target architecture.

---

## 2. Summary of Adaptations for General-Purpose & Object-Level Vision

To generalize DADA from patch-level classification to an industry-grade, multi-task engine supporting **Image Classification, Object Detection, and Instance Segmentation** at the **individual object level**, this specification mandates four architectural adaptations:

| Original DADA Component | Adaptation in This Specification | Engineering Rationale |
| :--- | :--- | :--- |
| **NAR Custom Model Pruning** ( $\phi$ scaling on CNN blocks) | **Native Architecture Family Proxy Scaling** (e.g., `YOLOv11-n`/`s` proxy for `YOLOv11-l`/`x` target) | Eliminates writing custom graph-pruning code for every new architecture while preserving structural feature alignment. Keeps original resolution input size.|
| **MC Dropout ( $F=20$) / Full Ensembles ( $N=3$)** | **Single-Pass Pre-NMS Proposal Cluster Variance** & **3-Pass TTA Jitter** | Avoids modifying model architectures to inject inference dropout and eliminates $20\times$ forward-pass bottlenecks on dense detectors. |
| **Single-Tier Image Subpool** ( $S_U$) | **Two-Tier Dynamic Subpooling** (Image Subpool $S_{\text{img}}$ + Object Gatekeeper $S_{\text{obj}}$) + **GPU `RoIAlign` Hooks** | Prevents memory explosions when $2,000$ images yield $>50,000$ candidate object boxes/masks; extracts per-object embeddings in milliseconds. |
| **Fully Labeled Patch Dataset** | **Partially Annotated Image (PAI) Schema & Region-Aware Training** | Because users only annotate selected uncertain objects, images contain unqueried objects. Standard losses would penalize unqueried objects as false positives without spatial masking. |

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
        │   ├── yolo_adapter.py           # Ultralytics YOLO Detection & Segmentation adapter
        │   └── timm_adapter.py           # PyTorch Image Models (timm) Classification adapter
        ├── uncertainty/
        │   ├── metrics.py                # Entropy, BALD, Variation Ratios, Box/Mask Variance
        │   ├── pre_nms_extractor.py      # Single-pass pre-NMS proposal cluster hook & scorer
        │   └── tta_extractor.py          # 3-pass scale/flip TTA box/mask matcher & scorer
        ├── acquisition/
        │   ├── subpool_manager.py        # Two-tier dynamic subpooling (Image + Object gatekeeper)
        │   ├── feature_extractor.py      # FPN RoIAlign & penultimate layer embedding hooks
        │   └── dada_selector.py          # PCA + MiniBatchKMeans + proportional cluster quota logic
        ├── dataset/
        │   ├── pai_schema.py             # Partially Annotated Image (PAI) Extended COCO schema
        │   ├── consensus_bridge.py       # Interface to Crowd-Kit / Cleanlab consensus & review routing
        │   └── pai_trainer.py            # Spatial ignore masking, Mosaic ROI builder & loss wrapper
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
    PRE_NMS = "pre_nms"                  # Single-pass pre-NMS proposal cluster variance
    TTA_JITTER = "tta_jitter"            # 3-pass scale + horizontal flip TTA
    SNAPSHOT_ENSEMBLE = "snapshot_ens"   # Last N epoch checkpoints

class DADAAlConfig(BaseModel):
    task: TaskType
    target_model_name: str = Field(..., description="e.g., 'yolo11x.pt', 'yolo11l-seg.pt', 'convnext_base'")
    proxy_model_name: str = Field(..., description="Fast NAR proxy, e.g., 'yolo11n.pt', 'yolo11n-seg.pt', 'convnext_tiny'")
    uncertainty_method: UncertaintyMethod = UncertaintyMethod.PRE_NMS
    retain_helper_models: bool = False  # Retain proxy/helper checkpoints only when enabled
    
    # Subpooling parameters
    image_subpool_size: int = 2000
    subpool_renewal_interval: int = 2    # Alpha parameter in DADA
    max_object_candidates: int = 15000   # Tier-2 object gatekeeper ceiling
    candidate_conf_floor: float = 0.08   # Minimum confidence to enter object pool
    annotated_iou_dedup_thresh: float = 0.50
    
    # DADA Clustering & Quota parameters
    pca_components: int = 50
    num_clusters: int = 20               # K parameter in DADA
    acquisition_budget_q: int = 500      # Total objects (or images) acquired per AL step
    
    # Uncertainty weighting hyperparameters
    loc_weight_lambda: float = 1.0       # Weight of localization uncertainty vs classification
    mask_boundary_band_px: int = 3       # Morphological dilation/erosion kernel radius for boundary entropy
    roi_context_padding: float = 0.15    # 15% box expansion when defining queried_roi for annotators
```

#### Core Internal Data Transfer Object (`CandidateItem`)
Every evaluated unit (an whole image for classification, or a candidate bounding box/mask for detection and segmentation) must be standardized into a `CandidateItem`:
* `candidate_id`: `str` (UUID)
* `image_id`: `str`
* `bbox_xyxy`: `Optional[Tuple[float, float, float, float]]` (None for image classification)
* `mask_rle`: `Optional[dict]` (COCO RLE polygon/mask for segmentation)
* `pred_class_probs`: `np.ndarray` of shape `(C,)`
* `cls_uncertainty`: `float`
* `spatial_uncertainty`: `float` ($0.0$ for classification)
* `total_uncertainty`: `float`
* `feature_vector`: `np.ndarray` of shape `(D,)`

---

### 4.2 Model Adapters & Zero-Code NAR Proxy (`models/`)

DADA implements the [shared batch selection contract](active_learning_requirements_specification.md#batch-selection-interface). Its internal model adapters handle proxy and target training and candidate extraction; these operations are not part of the API-facing contract.

#### 1. Classification

Supports the EfficientNet model family. Use EfficientNet-B1 as the proxy and EfficientNet-B5 as the target model. Should
implement the BaseModelAdapter interface. Other classification architectures could be added from TIMM models or by creating
their PyTorch architecture as a `models/custom_model_name.py` with both proxy and equivalent target.

* **PyTorch Forward Hooks for Feature Extraction:**
  * Should register a forward hook at the output of the last convolutional layer to extract features before clustering. 

#### 2. `YoloAdapter` (`models/yolo_adapter.py`)
Supports Ultralytics YOLOv8, YOLOv9, YOLOv11, YOLO26 for both Detection and Instance Segmentation:
* **Proxy Selection:** Automatically pairs the user's target architecture with its corresponding Nano (`n`) or Small (`s`) variant from the exact same model family so FPN feature pyramid hierarchies (`P3`, `P4`, `P5`) share identical structural inductive biases.
* **PyTorch Forward Hooks for Feature Extraction:**
  * Register a forward hook on the neck feature maps inputting into the `Detect` or `Segment` head (specifically the `P3` stride-8, `P4` stride-16, and `P5` stride-32 feature tensors).
  * Given $M$ candidate bounding boxes on an image, route each box to its scale-appropriate FPN level (or concatenate pooled features across `P3–P5`) and execute `torchvision.ops.roi_align(features, boxes, output_size=(2, 2), spatial_scale=...)`.
  * Flatten and L2-normalize the pooled tensor on the GPU to yield a compact semantic embedding $\mathbf{z} \in \mathbb{R}^D$ per object candidate without performing CPU image crops.

---

### 4.3 Fast Uncertainty Engine (`uncertainty/`)

To guarantee rapid uncertainty generation without modifying network dropout layers, implement the following calculators:

#### 1. Single-Pass Pre-NMS Proposal Cluster Extractor (`pre_nms_extractor.py`)
* **Mechanism:** Attach a forward hook to the raw prediction tensor of the YOLO head *immediately prior to Non-Maximum Suppression (NMS)* (shape: `[batch, 4 + C (+ 32 mask_protos), num_anchors]`, where `num_anchors` is typically $8400$).
* **Proposal Clustering:**
  1. Run standard NMS with a low confidence floor (`candidate_conf_floor = 0.08`) to obtain $M$ surviving candidate objects per image.
  2. For each surviving object $j \in \{1, \dots, M\}$ with box $b_j$, compute the IoU on the GPU between $b_j$ and all pre-NMS anchor boxes whose max class score exceeds `0.05`.
  3. Collect the local cluster of $K_j$ pre-NMS proposals that overlap with $b_j$ at $\text{IoU} \ge 0.50$.
* **Uncertainty Formulations over Proposal Cluster $K_j$:**
  * **Classification Uncertainty ( $U_{\text{cls}}$):** Compute BALD (Mutual Information) or Shannon Entropy across the $K_j$ probability vectors $\mathbf{p}^{(1..K_j)}$:
    $$U_{\text{cls}}(o_j) = H\left(\frac{1}{K_j}\sum_{m=1}^{K_j} \mathbf{p}^{(m)}\right) - \frac{1}{K_j}\sum_{m=1}^{K_j} H\left(\mathbf{p}^{(m)}\right)$$
  * **Detection Spatial Uncertainty ( $U_{\text{loc}}$):** Compute coordinate variance normalized by box scale, or mean pairwise IoU dispersion across the $K_j$ bounding boxes:
    $$U_{\text{loc}}(o_j) = 1 - \frac{1}{K_j} \sum_{m=1}^{K_j} \text{IoU}\left(b_j, \hat{b}^{(m)}\right)$$
  * **Segmentation Boundary Uncertainty ( $U_{\text{seg}}$):** Decode the instance mask $M_j \in [0, 1]^{H \times W}$. Compute the morphological boundary band $B(M_j) = \operatorname{Dilate}(M_j > 0.5, r) \setminus \operatorname{Erode}(M_j > 0.5, r)$ with radius $r = \text{mask_boundary_band_px}$. Calculate mean binary Shannon entropy strictly over pixels $i \in B(M_j)$:
    $$U_{\text{boundary}}(o_j) = -\frac{1}{|B(M_j)|} \sum_{i \in B(M_j)} \left[ p_i \log p_i + (1 - p_i) \log(1 - p_i) \right]$$
    Combine with $U_{\text{loc}}(o_j)$ for total spatial uncertainty: $U_{\text{spatial}}(o_j) = 0.5 \, U_{\text{loc}}(o_j) + 0.5 \, U_{\text{boundary}}(o_j)$.
  * **Joint Object Uncertainty ( $U_{\text{total}}$):**
    $$U_{\text{total}}(o_j) = U_{\text{cls}}(o_j) \cdot \left(1 + \lambda \, U_{\text{spatial}}(o_j)\right)$$

#### 2. Three-Pass TTA Jitter Extractor (`tta_extractor.py`)
* Fallback for models where pre-NMS hooks are not applicable:
  * Pass 1: Original image $I$.
  * Pass 2: Horizontally flipped image $\operatorname{Flip}(I)$ (invert boxes/masks back to original coordinate space).
  * Pass 3: Rescaled image $\operatorname{Scale}_{0.85}(I)$ (rescale boxes/masks back to original coordinate space).
* Match object detections across the 3 passes using Hungarian bipartite matching ( $\text{IoU} \ge 0.5$ ). If a candidate is missing in one of the passes, assign it a uniform/background probability distribution to penalize inconsistency, then compute BALD and spatial IoU variance across the 3 passes.

---

### 4.4 Two-Tier Dynamic Subpooling & DADA Selector (`acquisition/`)

#### 1. Two-Tier Subpool Manager (`subpool_manager.py`)
* **Tier 1 (Image Subpool $S_{\text{img}}$):**
  * Maintain state of the master image pool $U$ (which includes `UNLABELED` and `PARTIALLY_LABELED` images, excluding `EXHAUSTIVELY_LABELED` images).
  * Sample `image_subpool_size` images uniformly at random. Cache and reuse $S_{\text{img}}$ for `subpool_renewal_interval` ($\alpha = 2$) AL iterations before resampling.
* **Tier 2 (Object Candidate Gatekeeper $S_{\text{obj}}$):**
  * Run proxy inference on $S_{\text{img}}$ to collect raw `CandidateItem` objects.
  * **Deduplication against Existing Annotations:** For any `PARTIALLY_LABELED` image, load its existing human-verified annotations (both positive boxes and verified hard-negative ROIs). Discard any candidate $o_j$ that overlaps with an existing annotation or queried ROI at $\text{IoU} \ge \text{annotated_iou_dedup_thresh}$ ( $0.50$).
  * **Candidate Ceiling Pre-Filter:** If total surviving candidates $|S_{\text{obj}}| > \text{max_object_candidates}$ ( $15,000$), sort candidates by $U_{\text{total}}$ and retain the top `max_object_candidates` to guarantee that PCA and clustering execute in $< 5$ seconds.

#### 2. DADA Clustering & Quota Selector (`dada_selector.py`)
Implement Algorithm 1 from Meirelles et al. (2022) adapted to `CandidateItem` objects:
1. Stack feature vectors $\mathbf{Z} \in \mathbb{R}^{|S_{\text{obj}}| \times D}$.
2. Apply `sklearn.decomposition.PCA(n_components=min(config.pca_components, len(S_obj), D))` to obtain reduced matrix $\mathbf{Z}'$.
3. Apply `sklearn.cluster.MiniBatchKMeans(n_clusters=config.num_clusters, batch_size=1024)` on $\mathbf{Z}'$ to assign cluster labels $c_j \in \{0, \dots, K-1\}$.
4. For each cluster $k \in \{0, \dots, K-1\}$:
   * Calculate mean cluster uncertainty: $Z(k) = \frac{1}{|C_k|} \sum_{o_j \in C_k} U_{\text{total}}(o_j)$.
5. Compute cluster proportion $PR(k) = \frac{Z(k)}{\sum_{m=0}^{K-1} Z(m)}$.
6. Allocate integer quotas $\text{acqSize}(k)$ summing to exactly $Q = \text{acquisition_budget_q}$ using the Largest Remainder Method (so rounding never alters total budget $Q$).
7. Within each cluster $C_k$, sort candidates descending by $U_{\text{total}}(o_j)$ and select the top $\text{acqSize}(k)$ objects.
8. **Query ROI Generation:** For each selected object with bounding box $[x_1, y_1, x_2, y_2]$, expand the box by `roi_context_padding` ( $15\%$) clipped to image dimensions to create the `queried_roi` window presented to human annotators.

---

### 4.5 Shared annotation and training requirements

DADA generates query regions as described in section 4.4. The API owns annotation, consensus and the labeled pool. DADA consumes the resulting snapshots and handles partial-label training internally.

### 4.5 Partially Annotated Image (PAI) Dataset & Training Pipeline (`dataset/`)

When annotators only label selected objects, the resulting images are **Partially Annotated Images (PAIs)**: they contain verified objects inside `queried_rois`, verified background/hard-negatives inside dismissed `queried_rois`, and **unknown/unqueried pixels** everywhere else.

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
      "consensus_confidence": 0.94
    }
  ]
}
```
* **`resolution == "EXPLICIT_HARD_NEGATIVE"`:** Occurs when DADA flags a candidate object, presents the `queried_roi` to the annotator(s), and the annotators mark the region as containing no valid object (false positive). This region is a confirmed background zone.

#### 2. Background-Safe PAI Training Pipeline (`pai_trainer.py`)
Standard object detectors treat every anchor outside ground-truth boxes as negative background ($y=0$). Training naively on `PARTIALLY_LABELED` images penalizes the model when it detects real, unqueried objects outside `queried_rois`. Implement **two selectable training modes**:

##### Mode A: Zero-Rewrite Spatial Masking + High-Confidence Pseudo-Labeling (Default for Ultralytics YOLO)
Before launching a proxy or target training run, generate a temporary training view of all `PARTIALLY_LABELED` images:
1. **High-Confidence Pseudo-Label Injection:** Run the current best model over `PARTIALLY_LABELED` images. Any prediction outside `queried_rois` with confidence $\ge 0.80$ is temporarily added to the image's training labels for the upcoming epoch cycle.
2. **Unqueried Region Neutralization (Spatial Blackout):** For every `PARTIALLY_LABELED` image, construct a binary validity mask $W \in \{0, 1\}^{H \times W}$ where $W = 1$ inside all `queried_rois` (both `CONFIRMED_OBJECT` and `EXPLICIT_HARD_NEGATIVE` boxes) and $W = 1$ inside high-confidence pseudo-label boxes. Everywhere else ($W = 0$), replace pixel values with the dataset mean RGB value `(114, 114, 114)` or a heavy Gaussian blur $(\sigma = 25)$ so unqueried objects cannot trigger false-negative background gradients.

##### Mode B: Custom Loss Spatial Weighting Override (`PAIYoloTrainer`)
Subclass `ultralytics.models.yolo.detect.DetectionTrainer` (and `SegmentationTrainer`):
1. Pass the union of `queried_rois` per image into the data loader batch dictionary.
2. In `v8DetectionLoss.__call__`, compute a boolean mask `valid_bg_anchors` over the $8400$ anchor center points:
   * An anchor point $(c_x, c_y)$ is valid for negative/background Binary Cross-Entropy (BCE) loss **if and only if** the image is `EXHAUSTIVELY_LABELED` **OR** $(c_x, c_y)$ falls inside at least one `queried_roi` box.
3. Multiply the background classification BCE loss tensor by `valid_bg_anchors` before reduction. Positive matched anchors always receive full box, class, and DFL/mask loss weight ($1.0$).

---



---

## 5. End-to-End Active Learning Loop Orchestration (`pipeline/al_loop.py`)

The main orchestrator (`ActiveLearningOrchestrator.step()`) shall execute the following state machine per iteration $i$:

1. **Train Proxy Selector:** Train the lightweight proxy model (`proxy_model_name`, e.g., `yolo11n.pt`) on the current labeled dataset $L^i$ using `pai_trainer.py` for $E_{\text{proxy}}$ epochs.
2. **Tier-1 Subpool Sampling:** Query `SubpoolManager` to retrieve or renew the active image subpool $S_{\text{img}}^i \subset U^i$.
3. **Candidate & Feature Extraction:** Run the trained proxy model over $S_{\text{img}}^i$ with forward hooks enabled (`pre_nms_extractor` + `roi_align` feature hook) to produce raw `CandidateItem` instances.
4. **Tier-2 Gatekeeper Filtering:** Filter out candidates overlapping already-queried ROIs ( $\text{IoU} \ge 0.5$) and cap total candidates at `max_object_candidates`.
5. **DADA Selection:** Execute PCA dimensionality reduction, `MiniBatchKMeans` clustering, and proportional uncertainty quota allocation to select exactly $Q$ diverse, high-uncertainty objects.
6. **Export Annotation Batch:** Generate padded `queried_roi` coordinates for the $Q$ selected objects, group by `image_id`, and export the annotation task manifest for the UI / consensus engine.
7. **Return batch:** Return selected targets to the API. The API manages annotation and accepted results; DADA receives an updated training snapshot on a later request.
8. **Scheduled target-model evaluation:** At the user-selected evaluation frequency, train and evaluate the target architecture using the supplied training and separate validation data, and report metrics with iteration and model provenance. Never report proxy performance as target-model evaluation. Cadence options and stopping rules remain subject to [P7-03](../phases/phase_7.md#p7-03--iteration-stopping-and-recovery). Proxy/helper checkpoints are temporary and removed after operational or retry needs end unless `retain_helper_models` is explicitly enabled; target-model retention follows the applicable run policy.

---

## 6. Verification & Acceptance Criteria for the Coding Agent

1. **Unit Test — Pre-NMS Hook & RoIAlign Speed:** Verify on a batch of 16 images ( $640 \times 640$) with `yolo11n.pt` and `yolo11n-seg.pt` that pre-NMS uncertainty scoring and GPU `roi_align` feature extraction complete in $< 50\text{ ms}$ per image on a single GPU without CPU-GPU tensor copy bottlenecks.
2. **Unit Test — Quota Conservation:** Verify that `dada_selector.py` returns *exactly* $Q$ candidates across all edge cases (including empty clusters, single-item clusters, or clusters where $Z(k) = 0$).
3. **Unit Test — Deduplication Gatekeeper:** Verify that if an object at `[100, 100, 200, 200]` is already recorded in `queried_rois` (either as a positive object or an explicit hard negative), any new candidate overlapping it with $\text{IoU} \ge 0.50$ is strictly excluded from selection in subsequent AL iterations.
4. **Integration Test — PAI Background Protection:** Verify that on a synthetic `PARTIALLY_LABELED` image containing 5 objects where only 1 object is inside `queried_rois`, `pai_trainer.py` produces zero negative background gradient on the 4 unqueried objects.