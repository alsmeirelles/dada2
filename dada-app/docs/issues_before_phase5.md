# Phase 5 issues

All issues should be solved during phase 5 implementation.

| ID | Pending solution | Required documented outcome |
| --- | --- | --- |
| `I5-01` | Data selection when uploading images doesn't allow multiple files | Explicit issue addressing statement confirming resolution in this document |
| `I5-02` | Text misalignment in project's card | Explicit issue addressing statement confirming resolution in this document |
| `I5-03` | Multiple folder selection when uploading | Explicit issue addressing statement confirming resolution in this document |
| `I5-04` | Cancel project creation before completion | Explicit issue addressing statement confirming resolution in this document |


## I5-01

When selecting image files for uploading in the data importation step of a project's creation, the selection window only
allows selecting a full folder or a single file in a folder. It should allow multiple file selections.

## I5-02

`View annotation batches` and `Annotation settings` link texts are misaligned in the dashboard page's project card.

## I5-03

When creating a project, at step 5, the user is prompted to select a folder containing images for the project. If that
folder doesn't have enough images, the user can't move to the next step. So instead of asking the user to choose a different
folder, he should be able to select an additional folder and the images from all selected folders will be uploaded and used
as the project's dataset.

## I5-04

Add a button to let the user cancel a project creation before it's actually finished and activate. All data eventually
selected or sent to the API should be discarded.
