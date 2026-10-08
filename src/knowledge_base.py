"""
Knowledge Base for Ribbon Synapse EM Analyzer
==============================================
Builds and maintains a persistent, structured knowledge base about
synaptic ribbon morphology. Updates run only when requested from the Literature tab.

First run:  deep research (~5 min), saves everything locally
Later runs: quick update search for new papers, merges into existing KB

The KB is injected into every Claude image-analysis call so the model
knows exactly what to look for before seeing a single image.
"""

import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import anthropic

# Where the KB lives on disk (next to the app)
KB_PATH = Path(__file__).parent.parent / "knowledge_base.json"

# Minimum age before we do a refresh check (days)
REFRESH_INTERVAL_DAYS = 3

# ─────────────────────────────────────────────────────────────────────────────
# Research queries — each one becomes a separate web search + synthesis pass
# ─────────────────────────────────────────────────────────────────────────────

RESEARCH_TOPICS = [
    {
        "id": "ribbon_em_appearance",
        "title": "Ribbon ultrastructure in EM",
        "query": (
            "synaptic ribbon electron microscopy ultrastructure rod photoreceptor "
            "mouse retina electron-dense bar dimensions morphology"
        ),
        "synthesis_prompt": (
            "You are an expert in retinal ribbon synapse ultrastructure. "
            "Based on the search results, write a precise scientific summary (200-300 words) "
            "of how synaptic ribbons appear in transmission electron microscopy of mouse rod "
            "photoreceptors. Cover: shape, electron density, typical dimensions (length, width in nm), "
            "the vesicle halo, active zone attachment, and how to distinguish ribbons from other "
            "electron-dense structures. Be precise with numbers. Use plain text, no markdown."
        ),
    },
    {
        "id": "ribbon_development_p0_p35",
        "title": "Ribbon development P0–P35",
        "query": (
            "synaptic ribbon photoreceptor postnatal development mouse retina "
            "P0 P4 P10 P14 ribbon formation active zone attachment maturation"
        ),
        "synthesis_prompt": (
            "Summarize the postnatal development of rod photoreceptor ribbon synapses "
            "in the mouse retina from P0 to P35. For each key stage (P0, P4, P10, P14, P21, P30+), "
            "describe what the ribbon looks like in EM: size, shape, attachment status, "
            "vesicle organization. Cite Davison et al. 2022 and other key papers where relevant. "
            "Plain text, ~250 words, precise and scientific."
        ),
    },
    {
        "id": "piccolino_structure_function",
        "title": "Piccolino protein and ribbon function",
        "query": (
            "Piccolino splice variant Piccolo synaptic ribbon photoreceptor "
            "Regus-Leidig ribbon morphology vesicle tethering"
        ),
        "synthesis_prompt": (
            "Summarize what is known about Piccolino (the ribbon-specific splice variant of Piccolo) "
            "in photoreceptor ribbon synapses. Cover: localization, molecular function, "
            "interaction partners at the ribbon, role in vesicle tethering. "
            "Reference Regus-Leidig et al. 2013 and Gierke 2020 where relevant. "
            "~200 words, plain text, scientific."
        ),
    },
    {
        "id": "piccolino_cko_phenotype",
        "title": "Piccolino cKO ribbon phenotype in EM",
        "query": (
            "Piccolo Piccolino knockout photoreceptor ribbon synapse morphology "
            "aberrant elongated fragmented detached electron microscopy retina"
        ),
        "synthesis_prompt": (
            "Describe the ultrastructural phenotype of synaptic ribbons when Piccolino "
            "is lost (knockout or knockdown) in rod photoreceptors, as seen in electron microscopy. "
            "What morphological changes occur? Elongation? Fragmentation? Detachment from active zone? "
            "Changes in vesicle halo? How do these differ from WT? "
            "Reference key papers. ~200 words, plain text, precise scientific language."
        ),
    },
    {
        "id": "em_image_analysis_criteria",
        "title": "EM image analysis criteria for ribbons",
        "query": (
            "electron microscopy synaptic ribbon measurement length width "
            "morphology classification criteria image analysis photoreceptor"
        ),
        "synthesis_prompt": (
            "Describe the standard criteria used in published studies to identify, measure, "
            "and classify synaptic ribbons in electron micrographs of photoreceptors. "
            "What features define a 'normal' ribbon vs 'elongated' vs 'short' vs 'detached'? "
            "What are reference length ranges? How is ribbon length measured (longest axis)? "
            "What structures might be confused with ribbons? ~200 words, plain text."
        ),
    },
    {
        "id": "recent_ribbon_papers",
        "title": "Recent ribbon synapse papers (last 2 years)",
        "query": (
            "synaptic ribbon photoreceptor retina 2023 2024 2025 "
            "ultrastructure active zone ribbon synapse development"
        ),
        "synthesis_prompt": (
            "List and briefly summarize (1-2 sentences each) the most relevant recent papers "
            "(2023-2025) on synaptic ribbon structure, function, or development in photoreceptors. "
            "Focus on papers relevant to: ribbon morphology in EM, Piccolo/Piccolino, "
            "ribbon formation/development, vesicle tethering. "
            "Format: Author et al. Year — brief summary. Plain text."
        ),
    },
]


def _load_kb() -> dict:
    """Load existing knowledge base from disk, or return empty structure."""
    if KB_PATH.exists():
        try:
            with open(KB_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "version": 1,
        "created": None,
        "last_updated": None,
        "update_count": 0,
        "topics": {},
        "combined_context": "",
        "update_log": [],
    }


def _save_kb(kb: dict):
    KB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(KB_PATH, "w") as f:
        json.dump(kb, f, indent=2)


def _needs_update(kb: dict, force: bool = False) -> tuple[bool, list[str]]:
    """
    Decide whether KB needs updating.
    Returns (should_update, list_of_topic_ids_to_update).
    First run: all topics. Later: only stale/missing ones.
    """
    if force or not kb.get("last_updated"):
        return True, [t["id"] for t in RESEARCH_TOPICS]

    last = datetime.fromisoformat(kb["last_updated"])
    age = datetime.now() - last
    if age > timedelta(days=REFRESH_INTERVAL_DAYS):
        # Only update the "recent papers" topic on refresh runs
        return True, ["recent_ribbon_papers"]

    return False, []


def _research_topic(
    client: anthropic.Anthropic,
    topic: dict,
    progress_callback=None,
) -> str:
    """
    Run one research topic:
    1. Web search
    2. Claude synthesizes into clean scientific text
    Returns synthesized text.
    """
    if progress_callback:
        progress_callback(f"Searching: {topic['title']}...")

    # Step 1: web search + initial answer
    search_response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{
            "role": "user",
            "content": (
                f"Search for information about: {topic['query']}\n\n"
                f"Find specific, factual information from scientific papers and reviews. "
                f"Focus on quantitative data (dimensions in nm, developmental timepoints, "
                f"morphological criteria). Retrieve 3-5 relevant sources."
            )
        }]
    )

    # Collect search results text
    search_text = "\n".join(
        b.text for b in search_response.content if hasattr(b, "text") and b.text
    )

    if progress_callback:
        progress_callback(f"Synthesizing: {topic['title']}...")

    # Step 2: synthesize into clean scientific paragraph
    synthesis_response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": (
                f"Here is information gathered from scientific literature:\n\n"
                f"{search_text}\n\n"
                f"---\n\n"
                f"{topic['synthesis_prompt']}"
            )
        }]
    )

    return "\n".join(
        b.text for b in synthesis_response.content if hasattr(b, "text") and b.text
    ).strip()


def _build_combined_context(kb: dict) -> str:
    """
    Assemble all KB topics into a single context string
    that gets injected into every image analysis call.
    """
    sections = []
    topic_order = [t["id"] for t in RESEARCH_TOPICS]

    for tid in topic_order:
        topic_meta = next((t for t in RESEARCH_TOPICS if t["id"] == tid), None)
        content = kb["topics"].get(tid, {}).get("content", "")
        if content and topic_meta:
            sections.append(
                f"[{topic_meta['title'].upper()}]\n{content}"
            )

    return "\n\n".join(sections)


def build_or_update_knowledge_base(
    client: anthropic.Anthropic,
    force_full_rebuild: bool = False,
    progress_callback=None,
) -> dict:
    """
    Main entry point for a user-requested build or update.

    First run:  researches all topics (5-8 min), saves locally.
    Later runs: checks if refresh needed, updates stale topics only.

    Returns the KB dict (also saved to disk).
    """
    kb = _load_kb()
    should_update, topics_to_update = _needs_update(kb, force=force_full_rebuild)

    is_first_run = kb.get("created") is None

    if not should_update:
        if progress_callback:
            progress_callback(
                f"Knowledge base up to date "
                f"(last updated: {kb.get('last_updated', 'unknown')[:10]}). "
                f"Loaded {len(kb['topics'])} topics."
            )
        return kb

    if progress_callback:
        if is_first_run:
            progress_callback(
                "FIRST RUN: Building ribbon synapse knowledge base from literature. "
                f"Researching {len(topics_to_update)} topics — this takes ~5 minutes. "
                "This only happens once."
            )
        else:
            progress_callback(
                f"Updating knowledge base ({len(topics_to_update)} topic(s))..."
            )

    now = datetime.now().isoformat()
    if not kb["created"]:
        kb["created"] = now

    updated_count = 0
    errors = []

    for topic_id in topics_to_update:
        topic = next((t for t in RESEARCH_TOPICS if t["id"] == topic_id), None)
        if not topic:
            continue

        try:
            last_error = None
            for attempt in range(3):
                try:
                    content = _research_topic(client, topic, progress_callback)
                    break
                except Exception as e:
                    last_error = e
                    if "429" in str(e) or "rate_limit" in str(e):
                        wait = 60 * (attempt + 1)
                        if progress_callback:
                            progress_callback(f"  Rate limit — waiting {wait}s before retry...")
                        time.sleep(wait)
                    else:
                        raise
            else:
                raise last_error

            kb["topics"][topic_id] = {
                "title": topic["title"],
                "content": content,
                "updated": now,
            }
            updated_count += 1
            if progress_callback:
                progress_callback(f"  ✓ {topic['title']}")
            if topic_id != topics_to_update[-1]:
                if progress_callback:
                    progress_callback(f"  Pausing 30s (rate limit protection)...")
                time.sleep(30)

        except Exception as e:
            errors.append(f"{topic_id}: {e}")
            if progress_callback:
                progress_callback(f"  ✗ {topic['title']}: {e}")

    # Rebuild combined context
    kb["combined_context"] = _build_combined_context(kb)
    kb["last_updated"] = now
    kb["update_count"] = kb.get("update_count", 0) + 1
    kb["update_log"].append({
        "time": now,
        "topics_updated": topics_to_update,
        "errors": errors,
        "is_first_run": is_first_run,
    })

    _save_kb(kb)

    if progress_callback:
        progress_callback(
            f"Knowledge base ready. "
            f"{updated_count} topic(s) updated. "
            f"Total context: {len(kb['combined_context'])} characters."
        )

    return kb


def get_knowledge_context(kb: Optional[dict] = None) -> str:
    """
    Get the combined knowledge context string for injection into analysis prompts.
    Loads from disk if kb not provided.
    """
    if kb is None:
        kb = _load_kb()
    return kb.get("combined_context", "")


def get_kb_summary(kb: Optional[dict] = None) -> str:
    """Human-readable summary of KB status."""
    if kb is None:
        kb = _load_kb()
    if not kb.get("created"):
        return "Knowledge base: not yet built."

    topics_done = len(kb.get("topics", {}))
    last = kb.get("last_updated", "unknown")[:10]
    updates = kb.get("update_count", 0)
    return (
        f"Knowledge base: {topics_done}/{len(RESEARCH_TOPICS)} topics · "
        f"last updated {last} · {updates} update(s)"
    )
