"""
Analysis engine: Claude API calls for ribbon detection
"""

import base64
import json
import re
from pathlib import Path
from PIL import Image
import io
from typing import Optional

import anthropic

from .config import (
    MODEL_ANALYSIS, MODEL_RESEARCH, ANALYSIS_SYSTEM_PROMPT, RESEARCH_PROMPT,
    MAX_API_IMAGE_SIZE
)
from .knowledge_base import get_knowledge_context
from .local_detector import detect_ribbons, candidates_to_ribbon_data

TRAINING_FILE = Path(__file__).parent.parent / "training_examples.json"
IMPROVEMENT_LOG = Path(__file__).parent.parent / "improvement_notes.md"


def _load_training_examples() -> str:
    """
    Load user-corrected ribbon examples for few-shot prompting.
    Format: list of {image, ribbons_accepted, ribbons_rejected, notes}
    Returns a text summary injected into the system prompt.
    """
    if not TRAINING_FILE.exists():
        return ""
    try:
        data = json.loads(TRAINING_FILE.read_text())
        examples = data.get("examples", [])
        if not examples:
            return ""
        lines = [f"The user has verified {len(examples)} images. Key patterns learned:"]
        # Summarize what was accepted/rejected
        accepted_morphs = {}
        rejection_reasons = []
        for ex in examples[-20:]:  # last 20 examples
            for r in ex.get("accepted", []):
                m = r.get("morphology", "normal")
                accepted_morphs[m] = accepted_morphs.get(m, 0) + 1
            for r in ex.get("rejected", []):
                reason = r.get("rejection_reason", "")
                if reason:
                    rejection_reasons.append(reason)
        if accepted_morphs:
            lines.append("Accepted ribbon morphologies: " + ", ".join(f"{k}:{v}" for k, v in accepted_morphs.items()))
        if rejection_reasons:
            # Most common rejection reasons
            from collections import Counter
            common = Counter(rejection_reasons).most_common(5)
            lines.append("Common false positives to AVOID: " + "; ".join(f"{r} (x{n})" for r, n in common))
        return "\n".join(lines)
    except Exception:
        return ""


def log_improvement(note: str):
    """Append a note to the self-improvement log."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {timestamp}\n{note}\n"
    with open(IMPROVEMENT_LOG, "a") as f:
        f.write(entry)


def save_training_example(image_path: str, accepted_ribbons: list, rejected_ribbons: list, notes: str = ""):
    """Save a reviewed image as a training example for future few-shot prompting."""
    data = {"examples": []}
    if TRAINING_FILE.exists():
        try:
            data = json.loads(TRAINING_FILE.read_text())
        except Exception:
            pass

    # Check if this image already has an entry — update it
    existing = next((i for i, e in enumerate(data["examples"]) if e.get("image") == image_path), None)
    entry = {
        "image": image_path,
        "accepted": [{"morphology": r.get("morphology"), "notes": r.get("notes", ""),
                      "vesicle_halo": r.get("vesicle_halo"), "anchored_to_az": r.get("anchored_to_az")}
                     for r in accepted_ribbons],
        "rejected": [{"rejection_reason": r.get("rejection_reason", r.get("notes", "membrane/false positive"))}
                     for r in rejected_ribbons],
        "notes": notes,
    }
    if existing is not None:
        data["examples"][existing] = entry
    else:
        data["examples"].append(entry)

    # Keep last 100 examples
    data["examples"] = data["examples"][-100:]
    TRAINING_FILE.write_text(json.dumps(data, indent=2))


def _encode_image(image_path: Path, max_size: tuple = MAX_API_IMAGE_SIZE) -> tuple[str, str]:
    """Load, resize if needed, and base64-encode image. Returns (b64_data, media_type)."""
    img = Image.open(image_path)
    # Convert to RGB if needed (handles TIFF with alpha, etc.)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    # Resize if too large
    if img.width > max_size[0] or img.height > max_size[1]:
        img.thumbnail(max_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")
    return b64, "image/png"


def analyze_image(
    image_path: Path,
    client: anthropic.Anthropic,
    scale_px: float,
    scale_nm: float,
    scale_unit: str = "nm",
    additional_context: str = "",
    knowledge_context: str = "",
    use_local_detection: bool = True,
) -> dict:
    """
    Two-stage pipeline:
    1. Local image processing (no API) — finds ribbon candidates by size/shape/darkness
    2. Claude AI verifies candidates and adds scientific context

    Returns parsed result dict.
    """
    # ── Stage 1: Local detection ──────────────────────────────────
    local_candidates = []
    local_ribbons_json = "[]"
    if use_local_detection:
        try:
            candidates = detect_ribbons(image_path, scale_px, scale_nm, max_candidates=20)
            local_candidates = candidates_to_ribbon_data(candidates)
            import json as _json
            local_ribbons_json = _json.dumps([{
                "id": r["id"],
                "line": r["line"],
                "length_approx_nm": r.get("length_relative", 0) * scale_nm / scale_px * 10,
                "score": r.get("_local_score", 0),
                "darkness": r.get("_darkness", 0),
                "elongation": r.get("_elongation", 0),
                "halo": r.get("_halo", 0),
            } for r in local_candidates], indent=2)
        except Exception as e:
            local_ribbons_json = f"(local detection failed: {e})"

    b64, media_type = _encode_image(image_path)

    scale_info = f"Scale calibration: {scale_px:.0f} pixels = {scale_nm:.0f} {scale_unit}"
    context_line = f"\nAdditional context: {additional_context}" if additional_context else ""

    # Build enriched system prompt with knowledge base
    kb_section = ""
    if knowledge_context:
        kb_section = (
            "\n\n=== BACKGROUND KNOWLEDGE FROM LITERATURE ===\n"
            "Use the following verified scientific knowledge when analyzing this image:\n\n"
            + knowledge_context
            + "\n=== END BACKGROUND KNOWLEDGE ==="
        )
    enriched_system = ANALYSIS_SYSTEM_PROMPT + kb_section

    user_content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        },
        {
            "type": "text",
            "text": (
                f"Analyze this electron micrograph for synaptic ribbons.\n"
                f"{scale_info}{context_line}\n\n"
                f"LOCAL IMAGE PROCESSING PRE-ANALYSIS found {len(local_candidates)} candidates:\n"
                f"{local_ribbons_json}\n\n"
                f"For each local candidate: verify if it is truly a synaptic ribbon "
                f"(check location, darkness, halo, shape). Accept, reject, or correct "
                f"each one. Also look for any ribbons the local detector may have missed.\n\n"
                f"Return ONLY the JSON object as specified."
            ),
        },
    ]

    # Load few-shot training examples if available
    training_examples = _load_training_examples()
    if training_examples:
        enriched_system += "\n\n=== VERIFIED EXAMPLES FROM THIS DATASET ===\n" + training_examples

    response = client.messages.create(
        model=MODEL_ANALYSIS,
        max_tokens=2000,
        system=enriched_system,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = "".join(b.text for b in response.content if hasattr(b, "text"))
    # Strip any accidental markdown fences
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            result = json.loads(match.group())
        else:
            result = {
                "ribbons": [],
                "image_quality": "poor",
                "overall_notes": f"Parse error: {raw[:200]}",
                "_parse_error": True,
            }

    # Compute real-world measurements
    img = Image.open(image_path)
    img_w, img_h = img.size
    nm_per_px = scale_nm / scale_px

    for r in result.get("ribbons", []):
        r["length_nm"] = round((r.get("length_relative", 0) / 100) * img_w * nm_per_px, 1)
        r["width_nm"] = round((r.get("width_relative", 0) / 100) * img_w * nm_per_px, 1)
        r["image_width_px"] = img_w
        r["image_height_px"] = img_h

    result["image_path"] = str(image_path)
    result["image_filename"] = image_path.name
    return result


def fetch_literature(client: anthropic.Anthropic, progress_callback=None) -> str:
    """
    Use Claude + web search to fetch current literature on ribbon morphology.
    Returns formatted text summary.
    """
    if progress_callback:
        progress_callback("Searching literature databases...")

    tools = [{"type": "web_search_20250305", "name": "web_search"}]

    response = client.messages.create(
        model=MODEL_RESEARCH,
        max_tokens=1500,
        tools=tools,
        messages=[{"role": "user", "content": RESEARCH_PROMPT}],
    )

    text_blocks = [b.text for b in response.content if hasattr(b, "text") and b.text]
    return "\n".join(text_blocks)


def parse_folder_name(folder_name: str) -> dict:
    """
    Parse age and genotype from folder name.
    Examples: P10_WT, P14_cKO, P4_wildtype, p10-conditional_knockout
    Returns {"age": "P10", "genotype": "WT", "raw": "P10_WT"}
    """
    from .config import AGE_PATTERNS, GENOTYPE_PATTERNS
    import re as _re

    name_lower = folder_name.lower()
    age = None
    genotype = "unknown"

    # Find age — check week patterns first (e.g. 8w, 12w)
    week_match = _re.search(r'(\d+)w', name_lower)
    if week_match:
        age = f"{week_match.group(1)}w"
    else:
        # Check postnatal day patterns (P0, P4, P10, etc.)
        p_match = _re.search(r'p(\d+)', name_lower)
        if p_match:
            age = f"P{p_match.group(1)}"
        else:
            for a in AGE_PATTERNS:
                if a.lower() in name_lower:
                    age = a
                    break

    # Find genotype
    for pattern, label in GENOTYPE_PATTERNS.items():
        if pattern in name_lower:
            genotype = label
            break

    return {"age": age or folder_name, "genotype": genotype, "raw": folder_name}
