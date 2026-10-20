# Phase 7 App blocking issues

This document is a **blocking requirement for App Phase 7 implementation**.
App Phase 7 code must not start until every issue below is marked **RESOLVED**
in this file with the implemented change and verification evidence. This gate is
in addition to resolving and approving `P7-01`–`P7-05` and `A7-01`–`A7-03` in
the canonical [Phase 7 decision record](../../dada-api/docs/phases/phase_7.md).

An issue is resolved only when this document records its root cause, affected
App/API surface, remediation, verification, owner, and completion date. A
workaround or an unverified observation does not satisfy the gate.

| ID | Blocking issue | Required documented outcome | Status |
| --- | --- | --- | --- |
| `I7-01` | Annotator selection in project creation | Replace ambiguous typed usernames with selection from existing eligible users | **RESOLVED** |
| `I7-02` | Annotation settings: class strategy availability | Present concise, actionable availability guidance without internal IDs or raw evidence diagnostics | **RESOLVED** |
| `I7-03` | `dada-api` quote-named directory replication | Identify and remove the configuration/command path that creates the spurious directory hierarchy; verify `make infra-up` no longer creates it | **RESOLVED** |

## I7-01

At the team definition stage of project creation, annotators should be selected
from existing users. The current implementation requires typed usernames. Add a
multiple-user selection control appropriate to the project owner/manager flow.

**Cause.** The App had no user-discovery surface available to ordinary project
creators. The only API user list was the administrator-only global management
route, so the wizard fell back to an unchecked free-text username field.

**Resolution record:** **RESOLVED.** `GET /api/v1/users/eligible-annotators`
now lets any authenticated active user retrieve only the `id`, `username`, and
`display_name` of active users; global user administration remains restricted
to administrators. The project wizard loads every page of that directory and
offers the other active users as a checkbox list. Selected users are added as
annotators and kept in sync with the consensus pool. Verification: the live
HTTP authorization/filtering test passed; the wizard selection test passed;
the complete App suite passed (200 tests), as did App lint and the production
build. Owner: DADA App/API maintainers. Completed: 2026-10-20.

## I7-02

In the project creation or draft editing page, in the class strategy consensus selection, the "Reliability weighted vote"
and "Dawid skene" methods show a very long text, as:

"Not enough project evidence: decisions per rater (rater 1aca8eed-346e-4afb-81b9-8b42a774b716, required 30, found 0); 
observations per outcome (rater 1aca8eed-346e-4afb-81b9-8b42a774b716, outcome e07bff7b-52d9-4d7c-ba6c-8953d10bb0d8, required 
5, found 0); observations per outcome (rater 1aca8eed-346e-4afb-81b9-8b42a774b716, outcome bb26a385-3007-4d8e-8dd9-e15601474ba3, 
required 5, found 0);"

That goes on longer. Present only what the user needs to know to access these
options, succinctly.

**Cause.** The App rendered every field in the API's internal `missing`
evidence array. Per-rater and per-outcome entries therefore repeated UUIDs,
thresholds, and observed counts in the option's help text.

**Resolution record:** **RESOLVED.** Conditional strategies still use the full
API report to decide whether they are enabled, but repeated per-rater and
per-class gaps are collapsed into one short requirement for each evidence type.
For example, the App says that reliability weighting needs 30 reference
decisions per selected annotator and 5 for every class, without showing IDs or
the repeated current counts. Loading, lookup failure, pre-project, dependency,
and quarantine states retain distinct actionable messages. Raw diagnostics
remain in the API response for operational use and are not rendered in the
form. Verification: resolver unit and component tests cover hidden internal
user/class IDs, collapsed repeated gaps, and the concise accessible
description; the complete App suite passed (200 tests). Owner: DADA App
maintainers. Completed: 2026-10-20.

## I7-03

When executing the infra containers with make infra-up, a folder is being created inside dada-api. This folder's name is 
only a double quote (") and inside it there's a folder hierarchy recreating all folders from my drive's root to the path 
where dada-api is. This shouldn't happen and this double quote folder shouldn't be created.

Removing the generated folder previously exposed the malformed root when the
annotation canvas requested media:

```text
FileNotFoundError: [Errno 2] No such file or directory: '/home/meirelles/IA/dada2/dada-api/"/home/meirelles/IA/dada2/dada-api/data/media"/69fc7098-7ada-49e3-8c20-3da24c52c25e/bd/fd/bdfd7968ae8e2e80b7ef9c123a2de301b39d8ac9e9044195acf6aa84f982f9ee'
```

**Cause.** The local `.env` surrounded both absolute storage roots with double
quotes. A dotenv parser removes those quotes, but the Makefile's GNU Make
`include`/`export` path preserved them. The API then received a value beginning
with `"`, treated it as relative, and resolved it below `dada-api`, reproducing
the absolute hierarchy inside a directory named `"`. `make infra-up` exposed
the same environment-loading path but starts only PostgreSQL and Redis; the
first later API storage access created the hierarchy.

**Resolution record:** **RESOLVED.** The local storage-root values no longer
carry quotes, and API configuration now removes one matching outer quote pair
before testing whether a storage root is absolute. This makes values exported
by GNU Make resolve identically to values read directly by the dotenv parser.
Verification: the regression test passed for quoted absolute media and upload
roots; all 17 storage tests passed; API lint and format checks passed; from an
artifact-free `dada-api` directory, `make infra-up` brought PostgreSQL and Redis
to healthy state and no `"` directory existed afterward. Owner: DADA API
maintainers. Completed: 2026-10-20.
