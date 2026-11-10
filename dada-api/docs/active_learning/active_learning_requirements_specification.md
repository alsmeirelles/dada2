# Active Learning Solutions: General Requirements

This specification defines the shared contract for active learning (AL) solutions offered by dada-api. [DADA](dada_active_learning_requirements_specification.md) is the initial solution. These are Phase 7 requirements, not a claim that the API or workers already implement them. The [Phase 7 decisions](../phases/phase_7.md) govern the project and dataset lifecycle.

## Modularity and lifecycle

- Each solution shall be self-contained, owning its configuration, dependencies, adapters, acquisition logic and internal state. Additional algorithms shall not depend on DADA internals.
- The API owns registration, discovery, validation, authorization, durable jobs and persistence. A solution receives its versioned configuration, eligible training annotations and acquisition pool and returns selections and provenance through a common boundary; it must not directly mutate project or annotation state.
- Classification selects media; detection and segmentation may select object targets with proposed geometry. Results identify their source media and targets, solution ID and version, configuration, inputs and model/run identifiers for audit and reproducibility. Validation and test data are excluded from acquisition.
- The API validates eligibility and results before creating annotation work, records failures and permits retry. Random acquisition remains a separate strategy. Static `single_batch` projects cannot use AL.
- Persist the chosen solution and version with the project and run. Reject unavailable or incompatible selections rather than silently substituting another solution.

## Batch selection interface

Every solution implements the shared `BaseModelAdapter` at the API boundary. Its single required operation requests an annotation batch:

```python
class BaseModelAdapter(ABC):
    @abstractmethod
    def select_batch(self, request: BatchRequest) -> BatchResult: ...
```

`BatchRequest` contains a versioned solution configuration, task and class mapping, requested batch size, an immutable training-set snapshot of accepted annotations and their media, and an eligible unlabeled-pool snapshot with media identifiers and any existing annotation or query history needed to avoid reselection. Partially labeled media may remain eligible for object targets. Snapshots identify their versions and accessible media; validation and test data are excluded from the acquisition pool. Any optional evaluation data is separately identified and never treated as acquisition data. The request carries the user-selected evaluation schedule and any explicitly enabled helper-model retention setting. Artifact destinations, when needed, are supplied by the API and artifacts are identifiable by iteration. The API supplies these inputs; the solution decides how to use them.

`BatchResult` contains an ordered batch of media or object targets, each identifying an eligible source and, where applicable, proposed geometry in the canonical image plane. It includes solution ID and version, request/snapshot identifiers and relevant provenance; optional scores or metrics must identify their meaning. A solution may return fewer items when the eligible pool is insufficient, with a reason. Errors are reported explicitly. The API validates the result, including eligibility, duplicates, geometry and batch size, before creating annotation work. Interface types and serialization are to be finalized with the Phase 7 implementation.

Training, model choice, feature extraction and selection are solution internals; the batch interface does not prescribe a proxy or uncertainty metric. Scheduled performance evaluations use the solution’s target model, never a proxy or helper model. The user chooses evaluation frequency; cadence and stopping follow [P7-03](../phases/phase_7.md#p7-03--iteration-stopping-and-recovery) and [P7-08](../phases/phase_7.md#p7-08--batch-and-evaluation-contract). Evaluation results identify the target model, data snapshot and iteration. Proxy and helper models and their checkpoints are not retained by default after their operational use; an explicit configuration parameter may enable retention. Temporary artifacts needed during a run or retry may be kept until no longer needed, then deleted unless retention is enabled. Retention does not change canonical annotations or dataset export. `BaseModelAdapter` here is the solution-facing batch contract, not an internal model adapter.

## API discovery

The API shall expose a read-only catalog of registered AL solutions to the app. Each entry includes a stable ID, version, display name, description, supported tasks, availability, and a machine-readable configuration schema with defaults and constraints. The catalog derives from registered implementations; initially it contains DADA only. Unavailable implementations are omitted or marked unavailable with a reason. Discovery and selection use the same IDs and versions. The app uses the catalog to present compatible choices and configuration; the API independently validates each selection and configuration. Endpoint paths and transport schemas are to be specified with Phase 7 API work.

## Annotation ownership

The API manages assignment, annotation, consensus or single-annotation resolution, review, and the canonical labeled pool regardless of acquisition strategy. It records selected targets and query history, including confirmed objects and verified negatives; unqueried regions remain unknown. After resolution, accepted annotations become available to the next training-set snapshot. Solutions do not persist canonical labels or run the annotation workflow. Object-region handling and consensus follow the existing API annotation specifications.

## Acceptance criteria

1. A second solution can be registered and discovered without modifying DADA internals; configuration and dependencies remain isolated.
2. The catalog describes DADA and its supported tasks and configuration. The app discovers it without a hard-coded algorithm list; the API rejects unknown, unavailable, incompatible or invalid selections.
3. Contract tests exercise each registered solution and its `BaseModelAdapter`, including input validation, selection provenance and failure reporting. Existing runs retain their chosen solution version.
4. Object-level annotation preserves unqueried regions and consensus and review state.
5. Scheduled evaluations use the target model at the user-selected frequency. Proxy/helper artifacts are cleaned up by default and retained only when explicitly configured; retry cleanup is verified.
