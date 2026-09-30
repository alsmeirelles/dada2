# Phase 5 issues

All issues should be solved during phase 5 implementation.

| ID | Pending solution | Required documented outcome |
| --- | --- | --- |
| `I5-01` | Data selection when uploading images doesn't allow multiple files | Explicit issue addressing statement confirming resolution in this document |
| `I5-02` | Text misalignment in project's card | Explicit issue addressing statement confirming resolution in this document |
| `I5-03` | Multiple folder selection when uploading | Explicit issue addressing statement confirming resolution in this document |
| `I5-04` | Cancel project creation before completion | Explicit issue addressing statement confirming resolution in this document |
| `I5-05` | Retrying a failed project creation creates a second project | Explicit issue addressing statement confirming resolution in this document |


## I5-01

When selecting image files for uploading in the data importation step of a project's creation, the selection window only
allows selecting a full folder or a single file in a folder. It should allow multiple file selections.

**Resolved (2026-09-30).** Step 5 of the wizard and the draft setup page now offer **Choose files** next to the folder
picker. It is a second file input without the folder-only `webkitdirectory` attribute, so any number of files can be
selected at once. A loose file keeps its file name as its relative path. Proven by `ingest.test.ts`.

## I5-02

`View annotation batches` and `Annotation settings` link texts are misaligned in the dashboard page's project card.

**Resolved (2026-09-30).** There were two causes:

- A second `.project-card__action` rule, with a different margin and font size, lived in `annotation.css`. That
  stylesheet only loads after the annotation workspace has been opened, so the card changed shape mid-session. The rule
  was removed.
- The links sat side by side as inline boxes, only some of them with an icon.

The links now sit in one `.project-card__actions` column, and every link has an icon of the same size.

## I5-03

When creating a project, at step 5, the user is prompted to select a folder containing images for the project. If that
folder doesn't have enough images, the user can't move to the next step. So instead of asking the user to choose a different
folder, he should be able to select an additional folder and the images from all selected folders will be uploaded and used
as the project's dataset.

**Resolved (2026-09-30).** Each folder or file selection is now **added** to the images already chosen, through
**Add another folder** and **Add more files**. **Clear selection** starts over.

Each folder is still stripped to its own root, which is what the YOLO label import matches against. Two folders may
therefore both contain `0001.jpg`. The API refuses two images at one path, so a later image whose path is already taken is
skipped and counted among the skipped files. The "not enough images" message now suggests adding another folder.

Proven by `ingest.test.ts` (`mergeSelections`).

## I5-04

Add a button to let the user cancel a project creation before it's actually finished and activate. All data eventually
selected or sent to the API should be discarded.

**Resolved (2026-09-30).** The wizard and the draft setup page now show **Cancel project creation** until activation.
After a confirmation:

- If the project already exists on the server, it is deleted with `DELETE /projects/{id}`. That call already purges the
  project's records, uploaded media, and upload parts.
- The browser's saved setup snapshot is cleared.
- The user returns to Projects.

Before the project reaches the server, cancelling only discards the form. The wizard only ever deletes the project it
created itself, never another draft saved in the same tab. The settings page's existing delete now also clears the
snapshot. Proven by `project-cancel.test.tsx`.

## I5-05

Found while fixing I5-04. When project creation failed after the project already existed, the wizard said "try again to
resume where it stopped". Pressing Create again sent a new `POST /projects`, creating a second project.

**Resolved (2026-09-30).** The wizard now remembers the project it created and passes it to `createProjectWithDataset`
when retrying. That function then resumes the saved stage instead of creating another project.
