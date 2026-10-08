# Manual annotation

The manual tab is the primary workspace. **Load image folder** scans supported files recursively. Each image keeps its calibration, filename and folder context in the project. Images remain external files; the JSON contains annotations and paths, not embedded images.

## Drawing and editing

| Control | Action |
| --- | --- |
| Straight axis | Click the start and end of a ribbon axis |
| Curved axis | Left-click points; right-click to finish the axis; move to preview width and click to confirm |
| Sphere | Click the centre, then a radius point |
| Ribbon list / canvas annotation | Select a profile for editing |
| A / R | Accept / reject the selected profile |
| Delete | Remove the selected annotation |
| Escape | Cancel drawing |
| Left / Right | Previous image / save and advance |
| Mouse wheel | Zoom around the pointer |
| Space + drag | Pan the image |
| Fit | Fit the current image into the available canvas |

Annotation shortcuts apply to the canvas and lists. Text entries retain their usual editing keys. The image overview, ribbon list, editor and application sidebar can be collapsed to give the image more room.

A straight or curved axis records its drawn length. A spherical annotation records diameter as width and leaves height unmeasured. Choose the appropriate morphology and measurement eligibility yourself. Brightness and contrast affect the display; source images are not overwritten.

The curved-width control estimates width from the pointer's distance to the mean segment centre. Inspect its result and edit the width field when a perpendicular width is needed. The app does not infer a biological height from an arbitrary drawn curve.

## Calibration

Measure the image's scale bar in pixels and enter its physical value in nm or µm before loading a new folder. The JSON retains calibration per image, so reopening a project preserves its original values. For images with different magnifications, use separately calibrated projects or ensure their saved image calibration is correct. Changing Project Setup after loading a project does not recalibrate existing annotations.

Use **Height not measured** for classified profiles that are ineligible for height measurement. The profile remains in morphology counts while height summaries omit its missing measurement. Leave optional measurement fields empty when no value was obtained.

## Saving

**Save annotations** creates a project JSON on the first save, then writes to that same file. **Save as…** chooses another file. **Save & Next** writes the complete project before advancing; cancelling or failing that save leaves the current image open. **Previous** and selecting an image retain edits in memory; save the project to persist them. **Skip edits** skips the current ribbon edits.

The app asks about unsaved annotations before replacing a project or closing. Saves use a temporary file in the target directory and replace the destination only after a complete write. Storage errors are reported and the previous JSON remains intact.

Opening a project with missing images offers folder relocation. The app tries the saved relative structure, a direct folder/filename match and an unambiguous recursive match. If duplicate filenames remain ambiguous, it keeps the old paths rather than attaching annotations to a guessed image. It shows an unavailable-image message; the annotations stay saved.

## Export and privacy

Exports include profile measurements, per-image counts, group summaries, a report and exploratory plots. Rejected annotations remain in the JSON for review but are excluded from the tables. The existing export convention includes all profiles that have not been rejected, including unreviewed detector candidates. Complete your review before treating those tables as final.

Projects and reports can contain local image paths, filenames and notes. Review them before sharing. Local review examples and improvement notes are stored alongside the app for the optional AI workflow; they are excluded from Git along with images, saved projects and exports. They are not model training or an independently validated ground-truth dataset.

## Export safety

The CSV export prefixes text beginning with spreadsheet formula indicators or leading control characters with an apostrophe. Excel stores formula-like text as literal strings. Original notes in the saved project are unchanged. Numeric measurements remain numeric. The workbook sanitises group sheet names and resolves collisions without merging distinct groups.
