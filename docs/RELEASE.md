# Publication preparation

The public scope is a desktop tool for manual EM ribbon annotation and measurement. Automatic candidate detection, vesicle estimates and generated literature notes remain experimental.

## Compatibility and fixes

Existing project JSON files keep their morphology labels, measurements, calibration, straight-axis coordinates, curved geometry, review flags, notes and empty-terminal counts. Loading does not recalculate stored measurements. Image-level review status and rejection reasons now also survive saving.

New manual measurements use both image dimensions and image-level calibration; µm is converted to nm. This corrects the previous assumption of square images. The analysis convention itself is unchanged: the operator chooses the profile, geometry, morphology and measurement eligibility. No thesis-specific offset is built into the application.

Saving is atomic, Save & Next persists to disk, keyboard shortcuts are scoped to annotation controls, invalid numeric input is handled without changing the recorded measurement, and missing image loads clear the previous image. Moved projects can be relocated across operating systems without guessing between ambiguous filenames.

Exploratory exports now include spherical profiles in morphology plots, include P7 in postnatal trajectories and handle groups without ribbons. Week-labelled ages remain in tables and morphology plots; the postnatal-day trajectory is restricted to P-labelled ages.

## Publication boundaries

The Git allowlist includes source, setup/launch scripts, documentation, tests, the synthetic demo generator and one synthetic screenshot. All other local files are ignored. In particular, research images, real annotation JSON, training/review examples, outputs, local assistant settings and backups are not selected for publication.

Run `python scripts/check_release.py` after staging changes. It reads the Git index and reachable commit history and flags files outside the allowlist, common credential patterns, personal home paths and symlinks. Full history requires a full Git clone. This is a targeted automated check; manually review the complete selected files before publishing. Do not force-add ignored research data.

The setup scripts contain no embedded API key and use relative application paths. Manual use requires no key. Optional network operations remain explicit actions in the app.

## Remaining release decisions

A GitHub account, repository destination and licence have not been selected. No public upload is performed by the preparation scripts. Choose a licence explicitly before advertising the project as reusable open-source software. Windows launch scripts have been reviewed, but require verification on Windows; the desktop GUI and regression suite were exercised on macOS.

## Extended validation

Four local EM TIFFs (4014 × 2672 pixels, palette mode) passed a manual-workflow integration run covering import, display, adjustment, navigation, geometry, editing, save/reload, export and missing-folder relocation. Network calls were blocked throughout. The images and test annotations remain private and are absent from this repository. Existing thesis annotation projects were also checked read-only for loading compatibility. These checks validate software behaviour, not annotation accuracy or automatic detection performance.

Curved-axis width now uses the final confirmation point instead of depending on a previous mouse-motion preview. Project loading rejects invalid calibration and malformed geometry before replacing the active project. Opening broken JSON now reports the error without losing the active annotations. CSV and Excel exports protect formula-like text, and Excel group sheet names are valid and unique. GitHub Actions are pinned to verified upstream commit SHAs and run with read-only repository permissions; Dependabot configuration is included.

Selecting a different ribbon on the canvas now commits valid pending editor input and blocks the selection when input is invalid. Image objects explicitly belong to their own Tk canvas, avoiding cross-window image handles.
