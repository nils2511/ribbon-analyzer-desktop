"""
Configuration for Ribbon Synapse EM Analyzer
Nils Hampel · FAU Erlangen-Nürnberg · Brandstätter Lab
"""

MODEL_ANALYSIS = "claude-haiku-4-5-20251001"
MODEL_RESEARCH = "claude-haiku-4-5-20251001"

DEFAULT_SCALE_PX  = 319
DEFAULT_SCALE_NM  = 500
DEFAULT_SCALE_UNIT = "nm"

AGE_PATTERNS = ["P0", "P4", "P10", "P14", "P21", "P28", "P30", "P35",
                "8w", "12w", "4w", "6w", "16w", "20w"]
WEEK_PATTERNS = {
    "4w": "4 weeks", "6w": "6 weeks", "8w": "8 weeks",
    "12w": "12 weeks", "16w": "16 weeks", "20w": "20 weeks",
}
GENOTYPE_PATTERNS = {
    "wt": "WT", "wildtype": "WT", "wild_type": "WT", "wild-type": "WT",
    "ctrl": "WT", "control": "WT",
    "cko": "cKO", "cko_pclo": "cKO", "conditional_knockout": "cKO",
    "knockout": "cKO", "ko": "cKO", "pclo_cko": "cKO",
}

MORPHOLOGY_CLASSES = ["normal", "elongated", "short", "spherical", "detached", "fragmented", "unclear"]
MORPHOLOGY_COLORS  = {
    "normal":     "#1D9E75",
    "elongated":  "#EF9F27",
    "short":      "#378ADD",
    "spherical":  "#9F77DD",
    "detached":   "#E24B4A",
    "fragmented": "#D85A30",
    "unclear":    "#888780",
}

IMAGE_EXTENSIONS   = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}
MAX_API_IMAGE_SIZE = (768, 768)

OUTPUT_CSV   = "ribbon_measurements.csv"
OUTPUT_EXCEL = "ribbon_analysis.xlsx"

UI_BG       = "#121a20"
UI_PANEL    = "#1c2832"
UI_ACCENT   = "#1D9E75"
UI_ACCENT2  = "#378ADD"
UI_TEXT     = "#edf3f7"
UI_TEXT_DIM = "#a9b9c6"
UI_BORDER   = "#354550"

APP_TITLE    = "Ribbon Synapse EM Analyzer"
APP_SUBTITLE = "Manual annotation and measurement of ribbon profiles"

# ══════════════════════════════════════════════════════════════
#  ANALYSIS SYSTEM PROMPT
#  Ground truth from Gierke 2020 + user's own example images:
#  Ribbons in this dataset look like curved/oval electron-dense
#  plates, NOT straight bars. They are inside rod spherules,
#  surrounded by a vesicle halo, clearly separated from membranes.
# ══════════════════════════════════════════════════════════════
ANALYSIS_SYSTEM_PROMPT = """You are an expert electron microscopist analyzing TEM images of mouse retina OPL (outer plexiform layer) for synaptic ribbons in rod photoreceptor terminals (rod spherules).

═══════════════════════════════════════════════════════
STUDY: Nils Hampel, FAU Erlangen-Nürnberg
Piccolino (Pclo splice variant) cKO in rod photoreceptors
Rhodopsin-Cre driver, developmental stages P0–P35, 25,000× magnification
═══════════════════════════════════════════════════════

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW SYNAPTIC RIBBONS LOOK IN THESE TEM IMAGES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHAPE: Electron-dense, elongated oval or slightly curved plate/bar.
  In cross-section: appears as a SHORT THICK LINE or OVAL — like a
  small dark oblong blob, roughly 200–500 nm long and only ~30–35 nm
  thick. It looks like a small dark "grain" or "seed" shape.
  NOT a membrane — it is a free-floating organelle inside the cytoplasm.

LOCATION: Deep inside the rod spherule (the round presynaptic terminal).
  The rod spherule is a recognizable round/oval structure packed with
  small round synaptic vesicles (~40 nm diameter). The ribbon sits
  centrally in this vesicle cloud, away from the plasma membrane.

ELECTRON DENSITY: Strongly electron-dense = very dark gray to black.
  Darker than mitochondria cristae, much darker than cytoplasm.
  Uniform density throughout (not hollow, no internal structure).

VESICLE HALO: The ribbon is surrounded by a CLOUD of small round
  synaptic vesicles (~40 nm). These vesicles are tethered to it.
  This halo is one of the most reliable identifying features.

ORIENTATION: Usually oriented roughly perpendicular to the AZ membrane
  (standing upright), but can appear tilted or nearly horizontal
  depending on section angle.

DIMENSIONS (from Gierke 2020, rod photoreceptors):
  WT:  ~235 ± 23 nm height (long axis), ~30–35 nm width
  cKO (Piccolino KO): may be SPHERICAL (~120 nm diameter) instead of plate-shaped
       or ELONGATED (>400 nm), FRAGMENTED (multiple pieces), DETACHED from AZ

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IS NOT A RIBBON — COMMON FALSE POSITIVES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✗ Plasma membrane / cell membrane — long continuous sinuous line at cell boundary
✗ Presynaptic membrane / active zone density — flat dense patch AT the membrane, not floating
✗ Mitochondria — large oval organelles with internal cristae (parallel lines inside)
✗ Horizontal cell processes — finger-like invaginations into the rod spherule, elongated membrane profiles
✗ Cytoskeletal filaments — very thin, straight lines
✗ Dense-core vesicles — small round very dark dots, much smaller than ribbons
✗ Membrane-bound organelles — have a bounding membrane around them; ribbons do NOT

KEY RULE: If the dark structure is AT or part of a cell membrane → NOT a ribbon.
A real ribbon FLOATS inside the cytoplasm of the rod spherule, surrounded by vesicles.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEVELOPMENTAL CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
P0–P4:  Ribbons immature, may be spherical/small, not yet AZ-anchored
P10–P14: Ribbons elongating, attaching to AZ, plate-like shape emerging
P21+:   Mature plate-shaped ribbons, ~235 nm, dense vesicle halo

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — return ONLY valid JSON, no markdown, no backticks
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "ribbons": [
    {
      "id": 1,
      "bbox": [cx_pct, cy_pct, w_pct, h_pct],
      "line": [x1_pct, y1_pct, x2_pct, y2_pct],
      "morphology": "normal|elongated|short|spherical|detached|fragmented|unclear",
      "confidence": "high|medium|low",
      "length_relative": <long axis as % of image width>,
      "width_relative": <short axis as % of image width>,
      "angle_deg": <0-180, 90=vertical>,
      "vesicle_halo": true|false,
      "anchored_to_az": true|false,
      "inside_spherule": true|false,
      "notes": "<why this IS a ribbon: location, halo, shape — NOT a membrane>"
    }
  ],
  "image_quality": "good|acceptable|poor",
  "n_rod_spherules_visible": <integer, how many rod terminals visible>,
  "developmental_stage_hint": "<P0/P4/P10/P14/P21+>",
  "genotype_hint": "WT_likely|cKO_likely|unclear",
  "overall_notes": "<1-2 sentences>",
  "structures_considered_and_rejected": "<list structures you considered but ruled out as false positives>"
}

Coordinates: percentages (0-100) of image dimensions. Top-left=(0,0).
CONSERVATIVE: If unsure, set confidence=low or omit. A missed ribbon is better than a false positive membrane."""

RESEARCH_PROMPT = """Search for detailed information about synaptic ribbon ultrastructure in TEM images of mouse rod photoreceptor terminals (OPL). Find:

1. Exact TEM appearance of rod photoreceptor ribbons in mouse retina — shape, electron density, dimensions (cite exact nm values)
2. How to visually distinguish ribbons from: presynaptic membrane, active zone density, mitochondria, horizontal cell processes in TEM
3. The vesicle halo: arrangement, distance, density around ribbon
4. Developmental morphology P0-P35: when do ribbons become plate-shaped?
5. Piccolino/Pclo KO phenotype: spherical ribbons, fragmentation, detachment — exact morphological criteria
6. Key papers with EM figures: Regus-Leidig 2013, Gierke 2020 (FAU), Davison 2022, Müller 2019
7. Cross-section vs longitudinal section appearance differences

Include actual quantitative values from published data. Scientific precision."""
