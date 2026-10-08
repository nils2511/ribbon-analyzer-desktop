"""
Experimental local ribbon candidate detector.

Combines multi-scale Hessian ridges, LoG blobs and heuristic size,
contrast and texture scores. Parameters are dataset-specific; this is
not a validated detector. Review every candidate before analysis.

API: detect_ribbons(...) -> list[RibbonCandidate]
     candidates_to_ribbon_data(...) -> list[dict]
"""

import math
import numpy as np
from PIL import Image
from pathlib import Path
from dataclasses import dataclass


@dataclass
class RibbonCandidate:
    id: int = 0
    cx_pct: float = 0; cy_pct: float = 0
    x1_pct: float = 0; y1_pct: float = 0
    x2_pct: float = 0; y2_pct: float = 0
    bbox_x: float = 0; bbox_y: float = 0
    bbox_w: float = 1; bbox_h: float = 1
    length_px: float = 0; width_px: float = 0
    length_nm: float = 0; width_nm: float = 0
    total_score: float = 0
    vesicle_score: float = 0
    darkness_score: float = 0
    shape_score: float = 0
    membrane_penalty: float = 0
    cristae_penalty: float = 0
    template_score: float = 0
    plate_span_score: float = 0
    halo_cover: float = 0
    end_penalty: float = 0
    membrane_near_penalty: float = 0
    angle_deg: float = 90
    confidence: str = "medium"
    morphology: str = "normal"
    notes: str = ""
    _cx_px: float = 0; _cy_px: float = 0
    _is_blob: bool = False


def detect_ribbons(
    image_path: Path,
    scale_px: float = 319.0,
    scale_nm: float = 500.0,
    max_candidates: int = 20,
    mode: str = "liberal",
) -> list[RibbonCandidate]:

    # ── Load & resize ────────────────────────────────────────────────────────
    img = Image.open(image_path)
    if img.mode != "L":
        img = img.convert("L")
    orig_w, orig_h = img.size
    MAX_PROC = 1500
    sf = MAX_PROC / orig_w if orig_w > MAX_PROC else 1.0
    if sf < 1.0:
        img = img.resize((int(orig_w * sf), int(orig_h * sf)), Image.LANCZOS)
        scale_px *= sf

    arr  = np.array(img, dtype=np.float32)
    h, w = arr.shape
    nm_per_px = scale_nm / scale_px

    try:
        from scipy.ndimage import (
            gaussian_filter, uniform_filter, label,
            binary_dilation, binary_opening, maximum_filter,
            gaussian_laplace,
        )
    except ImportError:
        return []

    # ── GT-calibrated physical size constants ────────────────────────────────
    ribbon_hw_nm  = 18.0
    ribbon_hw_px  = max(2.5, ribbon_hw_nm / nm_per_px)
    rib_min_nm    = 40.0
    rib_max_nm    = 1100.0                # GT p95 ~900nm (was 520 — FIXED)
    max_width_nm  = 250.0                 # relaxed from 80
    ratio_min     = 1.1
    rib_min_px    = max(int(rib_min_nm / nm_per_px), 6)
    rib_max_px    = max(int(rib_max_nm / nm_per_px), 50)
    ves_sigma_px  = max(3.0, 15.0 / nm_per_px)

    # ── Valid-pixel mask: edges + scale bar ───────────────────────────────────
    marg_y = max(int(h * 0.04), 12)
    marg_x = max(int(w * 0.04), 12)
    valid  = np.zeros((h, w), dtype=bool)
    valid[marg_y:h - marg_y, marg_x:w - marg_x] = True
    valid[int(h * 0.955):, int(w * 0.908):] = False

    # ── Local contrast normalisation (80px window) ────────────────────────────
    nw   = 80
    lm   = uniform_filter(arr,      size=nw)
    lsq  = uniform_filter(arr ** 2, size=nw)
    lstd = np.sqrt(np.maximum(lsq - lm ** 2, 1.0))
    arr_inv = -(arr - lm) / lstd   # dark ribbon → positive peak

    # ── Multi-scale Hessian ridge filter ──────────────────────────────────────
    # Use 3 sigma values to capture ribbons at different scales/orientations.
    # GT ribbons have subtle ridge response → take MAX across scales.
    sigmas_ridge = [ribbon_hw_px * 0.7, ribbon_hw_px, ribbon_hw_px * 1.5]
    ridge = np.zeros((h, w), dtype=np.float32)

    for sig in sigmas_ridge:
        sig2 = sig ** 2
        Lxx_s = gaussian_filter(arr_inv, sigma=sig, order=[0, 2]) * sig2
        Lyy_s = gaussian_filter(arr_inv, sigma=sig, order=[2, 0]) * sig2
        Lxy_s = gaussian_filter(arr_inv, sigma=sig, order=[1, 1]) * sig2

        ht   = (Lxx_s + Lyy_s) / 2.0
        disc = np.sqrt(np.maximum((Lxx_s - Lyy_s) ** 2 / 4.0 + Lxy_s ** 2, 0.0))
        lam1 = ht + disc
        lam2 = ht - disc

        S2  = lam1 ** 2 + lam2 ** 2
        c2  = 0.05 * float(S2[valid].max()) if valid.any() else 1.0
        with np.errstate(divide="ignore", invalid="ignore"):
            RB2 = np.where(lam2 != 0, (lam1 / lam2) ** 2, 0.0)

        ridge_s = np.where(
            lam2 < 0,
            np.exp(-RB2 / (2.0 * 0.5 ** 2)) * (1.0 - np.exp(-S2 / (2.0 * c2))),
            0.0,
        ).astype(np.float32)
        ridge_s = np.where(valid, ridge_s, 0.0)
        ridge   = np.maximum(ridge, ridge_s)

    # Save Hessian at primary sigma for orientation extraction
    sig  = float(ribbon_hw_px)
    sig2 = sig ** 2
    Lxx  = gaussian_filter(arr_inv, sigma=sig, order=[0, 2]) * sig2
    Lyy  = gaussian_filter(arr_inv, sigma=sig, order=[2, 0]) * sig2
    Lxy  = gaussian_filter(arr_inv, sigma=sig, order=[1, 1]) * sig2

    # ── Local maxima in ridge map ──────────────────────────────────────────────
    sep_px  = max(int(rib_min_px * 0.7), 10)
    loc_max = (maximum_filter(ridge, size=sep_px) == ridge) & (ridge > 0)
    r_valid = ridge[valid]
    if not len(r_valid) or r_valid.max() == 0:
        r_valid = np.array([0.0])

    # GT ribbons are at ~4–8% of max ridge response.
    # Use 4% of max (no percentile cut) so GT ribbons are included.
    thresh   = float(r_valid.max()) * 0.04
    peak_map = loc_max & (ridge >= thresh)

    peak_ys, peak_xs = np.where(peak_map)
    if len(peak_ys):
        peak_vals = ridge[peak_ys, peak_xs]
        order     = np.argsort(peak_vals)[::-1]
        peak_ys, peak_xs, peak_vals = peak_ys[order], peak_xs[order], peak_vals[order]
    else:
        peak_ys = peak_xs = peak_vals = np.array([])

    # ── Membrane exclusion map ────────────────────────────────────────────────
    mem_thresh_val = float(np.percentile(arr, 6))
    membrane       = arr < mem_thresh_val
    membrane       = binary_opening(membrane, iterations=1)
    mem_lab, _     = label(membrane)
    mem_sizes      = np.bincount(mem_lab.ravel())
    large_ids      = np.where(mem_sizes > rib_max_px * 4)[0]
    large_ids      = large_ids[large_ids > 0]
    large_membrane = (np.isin(mem_lab, large_ids)
                      if len(large_ids) else np.zeros_like(membrane))
    mem_excl       = binary_dilation(large_membrane, iterations=4)

    # ── Vesicle texture map ───────────────────────────────────────────────────
    vs      = max(4, int(ves_sigma_px * 3))
    lv      = uniform_filter(arr,      size=vs)
    lvsq    = uniform_filter(arr ** 2, size=vs)
    loc_var = np.maximum(lvsq - lv ** 2, 0.0)

    var_thresh   = float(np.percentile(loc_var[valid], 60))
    ves_mean_ref = float(loc_var[loc_var > var_thresh].mean()) \
                   if (loc_var > var_thresh).any() else 1.0

    # ── Ridge candidates (elongated ribbons) ──────────────────────────────────
    ridge_cands = _detect_ridge_candidates(
        arr, arr_inv, ridge, lm, loc_var, valid, mem_excl, large_membrane,
        peak_ys, peak_xs, peak_vals, r_valid,
        nm_per_px, h, w,
        ribbon_hw_px, rib_min_nm, rib_max_nm, max_width_nm, ratio_min,
        rib_min_px, rib_max_px,
        var_thresh, ves_mean_ref,
        Lxx, Lyy, Lxy,
        binary_dilation, max_candidates * 4,
    )

    # ── Spherical blob candidates (LoG) ───────────────────────────────────────
    blob_cands = _detect_blob_candidates(
        arr, arr_inv, lm, loc_var, valid, mem_excl, large_membrane,
        nm_per_px, h, w,
        var_thresh, ves_mean_ref,
        gaussian_laplace, maximum_filter, binary_dilation,
    )

    # ── Merge, dedup ─────────────────────────────────────────────────────────
    all_cands  = list(ridge_cands)
    used       = [(c._cx_px, c._cy_px) for c in all_cands]
    min_sep    = max(int(rib_min_px * 0.5), 12)

    for bc in blob_cands:
        if not any(math.hypot(bc._cx_px - ux, bc._cy_px - uy) < min_sep
                   for ux, uy in used):
            all_cands.append(bc)
            used.append((bc._cx_px, bc._cy_px))

    all_cands.sort(key=lambda c: c.total_score, reverse=True)
    all_cands = _dedup(all_cands, min_dist=min_sep)

    # ── Final formatting ──────────────────────────────────────────────────────
    results = []
    for i, c in enumerate(all_cands[:max_candidates]):
        c.id     = i + 1
        c.cx_pct = c._cx_px / w * 100
        c.cy_pct = c._cy_px / h * 100

        if c._is_blob:
            r_px     = c.length_px / 2.0
            c.x1_pct = (c._cx_px - r_px) / w * 100
            c.y1_pct = c.cy_pct
            c.x2_pct = (c._cx_px + r_px) / w * 100
            c.y2_pct = c.cy_pct
        else:
            a    = math.radians(c.angle_deg)
            hl   = c.length_px / 2
            c.x1_pct = (c._cx_px - math.cos(a) * hl) / w * 100
            c.y1_pct = (c._cy_px - math.sin(a) * hl) / h * 100
            c.x2_pct = (c._cx_px + math.cos(a) * hl) / w * 100
            c.y2_pct = (c._cy_px + math.sin(a) * hl) / h * 100

        c.bbox_x = c.cx_pct
        c.bbox_y = c.cy_pct
        c.bbox_w = max(abs(c.x2_pct - c.x1_pct) + 0.5, 0.5)
        c.bbox_h = max(abs(c.y2_pct - c.y1_pct) + 0.5, 0.5)
        c.confidence = (
            "high"   if c.total_score > 0.55 else
            "medium" if c.total_score > 0.35 else "low"
        )
        results.append(c)

    return results


def _dark_score(arr_c, ribbon_mask, ring_bool) -> float:
    """
    GT-calibrated darkness score.
    GT contrast: median 8 GU, p90 22 GU → divisor = 15 GU.
    Background ring must be OUTSIDE the vesicle halo (>20px from ribbon).
    """
    region_vals = arr_c[ribbon_mask]
    if not ring_bool.any() or not len(region_vals):
        return 0.0
    ring_mean   = float(arr_c[ring_bool].mean())
    ribbon_mean = float(region_vals.mean())
    contrast    = ring_mean - ribbon_mean
    return float(np.clip(contrast / 15.0, 0.0, 1.0))  # 15 GU = 100% (was 55)


def _detect_ridge_candidates(
    arr, arr_inv, ridge, lm, loc_var, valid, mem_excl, large_membrane,
    peak_ys, peak_xs, peak_vals, r_valid,
    nm_per_px, h, w,
    ribbon_hw_px, rib_min_nm, rib_max_nm, max_width_nm, ratio_min,
    rib_min_px, rib_max_px,
    var_thresh, ves_mean_ref,
    Lxx, Lyy, Lxy,
    binary_dilation,
    max_analyze_in: int = 250,
) -> list[RibbonCandidate]:

    sep_px      = max(int(rib_min_px * 0.7), 10)
    max_analyze = min(len(peak_ys), max_analyze_in)  # was 60 → now up to 250
    candidates  = []
    used_centres: list[tuple[float, float]] = []

    for pi in range(max_analyze):
        cy_i = int(peak_ys[pi])
        cx_i = int(peak_xs[pi])
        rv   = float(peak_vals[pi])

        if not valid[cy_i, cx_i]:
            continue
        if mem_excl[cy_i, cx_i]:
            continue
        if any(math.hypot(cx_i - ux, cy_i - uy) < sep_px for ux, uy in used_centres):
            continue

        # ── Orientation from Hessian ──────────────────────────────────────
        H = np.array([
            [float(Lyy[cy_i, cx_i]), float(Lxy[cy_i, cx_i])],
            [float(Lxy[cy_i, cx_i]), float(Lxx[cy_i, cx_i])],
        ])
        try:
            ev, evec = np.linalg.eigh(H)
        except Exception:
            continue
        if float(ev[0]) >= 0:
            continue

        maj_v  = evec[:, 1].astype(float)
        perp_v = evec[:, 0].astype(float)
        angle_deg = float(math.degrees(math.atan2(maj_v[1], maj_v[0])) % 180)

        # ── Trace ribbon length ────────────────────────────────────────────
        pad = rib_max_px + int(rib_min_px) + 12
        r0 = max(0, cy_i - pad); r1 = min(h, cy_i + pad)
        c0 = max(0, cx_i - pad); c1 = min(w, cx_i + pad)

        ridge_c    = ridge          [r0:r1, c0:c1]
        arr_c      = arr            [r0:r1, c0:c1]
        loc_var_c  = loc_var        [r0:r1, c0:c1]
        mem_excl_c = mem_excl       [r0:r1, c0:c1]
        large_c    = large_membrane [r0:r1, c0:c1]

        cx_crop = cx_i - c0
        cy_crop = cy_i - r0

        trace_thresh = rv * 0.18
        half_lengths = []
        for sign in [1, -1]:
            y_f, x_f = float(cy_crop), float(cx_crop)
            dist_last = 0.0; gap = 0
            for step in range(1, rib_max_px + 1):
                y_f += sign * maj_v[0]; x_f += sign * maj_v[1]
                yi, xi = int(round(y_f)), int(round(x_f))
                if not (0 <= yi < ridge_c.shape[0] and 0 <= xi < ridge_c.shape[1]):
                    break
                if ridge_c[yi, xi] >= trace_thresh:
                    dist_last = float(step); gap = 0
                else:
                    gap += 1
                    if gap > 3:
                        break
            half_lengths.append(dist_last)
        length_px = half_lengths[0] + half_lengths[1]

        perp_thresh = rv * 0.10
        half_widths = []
        for sign in [1, -1]:
            y_f, x_f = float(cy_crop), float(cx_crop)
            dist_last = 0.0
            for step in range(1, int(ribbon_hw_px * 5) + 1):
                y_f += sign * perp_v[0]; x_f += sign * perp_v[1]
                yi, xi = int(round(y_f)), int(round(x_f))
                if not (0 <= yi < ridge_c.shape[0] and 0 <= xi < ridge_c.shape[1]):
                    break
                if ridge_c[yi, xi] >= perp_thresh:
                    dist_last = float(step)
                else:
                    break
            half_widths.append(dist_last)
        width_px = half_widths[0] + half_widths[1]

        if width_px > length_px:
            length_px, width_px = width_px, length_px

        length_nm_c = length_px * nm_per_px
        width_nm_c  = max(width_px, 1.0) * nm_per_px

        if length_nm_c < rib_min_nm or length_nm_c > rib_max_nm:
            continue
        if width_nm_c > max_width_nm:
            continue
        ratio = length_px / max(width_px, 1.0)
        if ratio < ratio_min:
            continue

        # ── Ridge extension penalty ───────────────────────────────────────
        # Membranes have ridges that extend FAR beyond the detected segment.
        # True ribbons end abruptly. Measure extra ridge beyond each endpoint.
        extra_steps = 0
        max_ext = min(rib_max_px // 2, 120)
        for i_side, sign in enumerate([1, -1]):
            hl_side = half_lengths[i_side]
            y_f = float(cy_crop) + sign * hl_side * maj_v[0]
            x_f = float(cx_crop) + sign * hl_side * maj_v[1]
            for _ in range(1, max_ext + 1):
                y_f += sign * maj_v[0]; x_f += sign * maj_v[1]
                yi, xi = int(round(y_f)), int(round(x_f))
                if not (0 <= yi < ridge_c.shape[0] and 0 <= xi < ridge_c.shape[1]):
                    break
                if ridge_c[yi, xi] >= trace_thresh:
                    extra_steps += 1
                else:
                    break
        ext_penalty = float(np.clip(extra_steps / (max_ext * 2) * 2.5, 0.0, 1.0))

        # ── Ribbon mask ────────────────────────────────────────────────────
        yy, xx    = np.indices(arr_c.shape)
        dx        = (xx - cx_crop).astype(float)
        dy        = (yy - cy_crop).astype(float)
        proj_maj  = dx * maj_v[1]  + dy * maj_v[0]
        proj_perp = dx * perp_v[1] + dy * perp_v[0]
        ribbon_mask = (
            (np.abs(proj_maj)  <= length_px / 2.0 + 1) &
            (np.abs(proj_perp) <= max(width_px / 2.0, ribbon_hw_px) + 1)
        )

        mem_overlap = float((ribbon_mask & large_c).sum()) / max(int(ribbon_mask.sum()), 1)
        if mem_overlap > 0.30:
            continue

        # ── Background ring: OUTSIDE vesicle halo (20–50px from edge) ─────
        # v5 used 4–18px: this was inside the halo, underestimating contrast.
        ring_in  = binary_dilation(ribbon_mask, iterations=20)
        ring_out = binary_dilation(ribbon_mask, iterations=50)
        ring     = ring_out & ~ring_in & ~mem_excl_c
        ring_bool = ring.astype(bool)

        dark = _dark_score(arr_c, ribbon_mask, ring_bool)
        if dark < 0.03:   # was 0.12; GT ribbons often have dark_score 0.03–0.50
            continue

        # ── Vesicle halo score ────────────────────────────────────────────
        ves_score  = 0.0
        halo_cover = 0.0
        if ring_bool.sum() > 8:
            ring_var  = float(loc_var_c[ring_bool].mean())
            ves_score = float(np.clip(ring_var / max(ves_mean_ref, 1.0) * 0.9, 0.0, 1.0))
            ring_ys, ring_xs = np.where(ring_bool)
            ang     = np.arctan2(ring_ys - cy_crop, ring_xs - cx_crop)
            sec_occ = []
            for a0, a1 in zip(np.linspace(-math.pi, math.pi, 9)[:-1],
                               np.linspace(-math.pi, math.pi, 9)[1:]):
                sec = (ang >= a0) & (ang < a1)
                if sec.sum() < 3:
                    sec_occ.append(0.0)
                    continue
                sec_occ.append(
                    float((loc_var_c[ring_ys[sec], ring_xs[sec]] > var_thresh).mean())
                )
            if sec_occ:
                covered    = sum(v > 0.30 for v in sec_occ)
                halo_cover = float(np.clip((covered - 1) / 6.0, 0.0, 1.0))

        # ── Symmetry score ────────────────────────────────────────────────
        asym_pen = 0.0
        if ring_bool.sum() > 20:
            ring_ys, ring_xs = np.where(ring_bool)
            pp  = (ring_xs - cx_crop) * perp_v[1] + (ring_ys - cy_crop) * perp_v[0]
            pos = pp > 0; neg = pp < 0
            if pos.sum() > 5 and neg.sum() > 5:
                pv = float(loc_var_c[ring_ys[pos], ring_xs[pos]].mean())
                nv = float(loc_var_c[ring_ys[neg], ring_xs[neg]].mean())
                mv = (pv + nv) / 2.0
                asym_pen = float(np.clip(abs(pv - nv) / max(mv, 1.0) * 1.3, 0.0, 1.0))

        # GT-calibrated size score: normal median=373nm, σ=280nm
        size_score  = float(math.exp(-0.5 * ((length_nm_c - 373.0) / 280.0) ** 2))

        if 2.0 <= ratio <= 18.0:
            shape_score = 1.0
        elif ratio < 2.0:
            shape_score = (ratio - ratio_min) / (2.0 - ratio_min)
        else:
            shape_score = max(0.3, 1.0 - (ratio - 18.0) / 10.0)
        shape_score = float(np.clip(shape_score, 0.0, 1.0))

        ridge_score = float(np.clip(rv / max(float(r_valid.max()), 1e-6), 0.0, 1.0))

        region_vals = arr_c[ribbon_mask]
        if len(region_vals) > 1 and ring_bool.sum() > 5:
            int_std   = float(region_vals.std())
            bg_std    = float(arr_c[ring_bool].std())
            crist_pen = float(np.clip((int_std / max(bg_std, 1.0) - 1.1) * 0.6, 0.0, 1.0))
        else:
            crist_pen = 0.0

        total = (
            dark                  * 0.28 +
            ves_score             * 0.17 +
            halo_cover            * 0.13 +
            size_score            * 0.12 +
            shape_score           * 0.10 +
            ridge_score           * 0.07 +
            (1.0 - asym_pen)      * 0.05 +
            (1.0 - crist_pen)     * 0.02 +
            (1.0 - ext_penalty)   * 0.06  # membrane extension penalty
        )

        morph = _classify_morphology(length_nm_c, ratio)

        c = RibbonCandidate(
            length_px        = length_px,
            width_px         = width_px,
            length_nm        = round(length_nm_c, 1),
            width_nm         = round(width_nm_c,  1),
            total_score      = round(total,        3),
            vesicle_score    = round(ves_score,    3),
            darkness_score   = round(dark,         3),
            shape_score      = round(shape_score,  3),
            membrane_penalty = round(mem_overlap,  3),
            cristae_penalty  = round(crist_pen,    3),
            halo_cover       = round(halo_cover,   3),
            angle_deg        = angle_deg,
            morphology       = morph,
            notes=(
                f"ridge={rv:.3f} dark={dark:.2f} "
                f"ves={ves_score:.2f} halo={halo_cover:.2f} "
                f"size={size_score:.2f} shape={shape_score:.2f} "
                f"ext_pen={ext_penalty:.2f} asym={asym_pen:.2f} "
                f"len={length_nm_c:.0f}nm w={width_nm_c:.0f}nm ratio={ratio:.1f}"
            ),
        )
        c._cx_px   = float(cx_i)
        c._cy_px   = float(cy_i)
        c._is_blob = False
        used_centres.append((float(cx_i), float(cy_i)))
        candidates.append(c)

    return candidates


def _detect_blob_candidates(
    arr, arr_inv, lm, loc_var, valid, mem_excl, large_membrane,
    nm_per_px, h, w,
    var_thresh, ves_mean_ref,
    gaussian_laplace, maximum_filter, binary_dilation,
) -> list[RibbonCandidate]:
    """
    LoG multi-scale blob detector for spherical ribbons.
    GT spherical: median=210nm, p95=314nm, min~24nm.
    """
    sph_min_r_nm = 20.0
    sph_max_r_nm = 200.0
    sph_min_r_px = max(4.0, sph_min_r_nm / nm_per_px)
    sph_max_r_px = min(60.0, sph_max_r_nm / nm_per_px)

    sig_min = sph_min_r_px / math.sqrt(2)
    sig_max = sph_max_r_px / math.sqrt(2)
    sigmas  = np.geomspace(sig_min, sig_max, 5)

    # σ²-normalized LoG: dark blob → positive peak in arr_inv → -gauss_lap * σ²
    log_stack = np.zeros((h, w, len(sigmas)), dtype=np.float32)
    for i, sigma in enumerate(sigmas):
        resp = -gaussian_laplace(arr_inv, sigma=float(sigma)) * (float(sigma) ** 2)
        log_stack[:, :, i] = np.where(valid, resp, 0.0)

    log_max   = log_stack.max(axis=2)
    log_sigma = sigmas[log_stack.argmax(axis=2)]

    sep_blob = max(int(sph_min_r_px * 1.5), 8)
    loc_max  = (maximum_filter(log_max, size=sep_blob) == log_max) & (log_max > 0)
    lm_valid = log_max[valid]
    if not len(lm_valid) or lm_valid.max() <= 0:
        return []

    blob_thresh = max(float(np.percentile(lm_valid, 85)), float(lm_valid.max()) * 0.05)
    peak_map    = loc_max & (log_max >= blob_thresh)

    peak_ys, peak_xs = np.where(peak_map)
    if not len(peak_ys):
        return []

    order   = np.argsort(log_max[peak_ys, peak_xs])[::-1]
    peak_ys = peak_ys[order]
    peak_xs = peak_xs[order]

    candidates   = []
    used_centres: list[tuple[float, float]] = []
    log_max_val  = float(log_max[valid].max()) if valid.any() else 1.0

    for cy_i, cx_i in zip(peak_ys[:80], peak_xs[:80]):
        cy_i, cx_i = int(cy_i), int(cx_i)

        if not valid[cy_i, cx_i]:
            continue
        if mem_excl[cy_i, cx_i]:
            continue

        sigma_pk = float(log_sigma[cy_i, cx_i])
        r_px     = sigma_pk * math.sqrt(2)

        if any(math.hypot(cx_i - ux, cy_i - uy) < max(r_px * 1.5, sep_blob)
               for ux, uy in used_centres):
            continue

        pad  = int(r_px * 3.5) + 20
        r0 = max(0, cy_i - pad); r1 = min(h, cy_i + pad)
        c0 = max(0, cx_i - pad); c1 = min(w, cx_i + pad)

        arr_c      = arr             [r0:r1, c0:c1]
        loc_var_c  = loc_var         [r0:r1, c0:c1]
        mem_excl_c = mem_excl        [r0:r1, c0:c1]
        large_c    = large_membrane  [r0:r1, c0:c1]

        cx_crop = cx_i - c0
        cy_crop = cy_i - r0

        yy, xx    = np.indices(arr_c.shape)
        dist      = np.sqrt((xx - cx_crop) ** 2 + (yy - cy_crop) ** 2)
        blob_mask = dist <= max(r_px, 4.0)

        mem_overlap = float((blob_mask & large_c).sum()) / max(int(blob_mask.sum()), 1)
        if mem_overlap > 0.30:
            continue

        # Suppress highly elongated detections (ridge detector handles those)
        ys_b, xs_b = np.where(blob_mask)
        if len(ys_b) > 3:
            try:
                cov    = np.cov(xs_b.astype(float), ys_b.astype(float))
                evals  = np.linalg.eigvalsh(cov)
                aspect = max(np.abs(evals)) / max(min(np.abs(evals)), 1.0)
                if aspect > 5.0:
                    continue
            except Exception:
                pass

        # Background ring outside halo
        ring_in   = binary_dilation(blob_mask, iterations=max(int(r_px * 0.8), 8))
        ring_out  = binary_dilation(blob_mask, iterations=max(int(r_px * 2.5), 25))
        ring      = ring_out & ~ring_in & ~mem_excl_c
        ring_bool = ring.astype(bool)

        dark = _dark_score(arr_c, blob_mask, ring_bool)
        if dark < 0.03:
            continue

        ves_score  = 0.0
        halo_cover = 0.0
        if ring_bool.sum() > 8:
            ring_var  = float(loc_var_c[ring_bool].mean())
            ves_score = float(np.clip(ring_var / max(ves_mean_ref, 1.0) * 0.9, 0.0, 1.0))
            ring_ys, ring_xs = np.where(ring_bool)
            ang     = np.arctan2(ring_ys - cy_crop, ring_xs - cx_crop)
            sec_occ = []
            for a0, a1 in zip(np.linspace(-math.pi, math.pi, 9)[:-1],
                               np.linspace(-math.pi, math.pi, 9)[1:]):
                sec = (ang >= a0) & (ang < a1)
                if sec.sum() < 3:
                    sec_occ.append(0.0)
                    continue
                sec_occ.append(
                    float((loc_var_c[ring_ys[sec], ring_xs[sec]] > var_thresh).mean())
                )
            if sec_occ:
                covered    = sum(v > 0.30 for v in sec_occ)
                halo_cover = float(np.clip((covered - 1) / 6.0, 0.0, 1.0))

        diameter_nm = r_px * 2.0 * nm_per_px
        size_score  = float(math.exp(-0.5 * ((diameter_nm - 210.0) / 100.0) ** 2))

        region_vals = arr_c[blob_mask]
        if len(region_vals) > 1 and ring_bool.sum() > 5:
            int_std   = float(region_vals.std())
            bg_std    = float(arr_c[ring_bool].std())
            crist_pen = float(np.clip((int_std / max(bg_std, 1.0) - 1.1) * 0.6, 0.0, 1.0))
        else:
            crist_pen = 0.0

        log_score = float(np.clip(float(log_max[cy_i, cx_i]) / max(log_max_val, 1e-6), 0.0, 1.0))

        total = (
            dark               * 0.32 +
            ves_score          * 0.20 +
            halo_cover         * 0.15 +
            size_score         * 0.15 +
            log_score          * 0.10 +
            (1.0 - crist_pen)  * 0.08
        )

        c = RibbonCandidate(
            length_px      = r_px * 2.0,
            width_px       = r_px * 2.0,
            length_nm      = round(diameter_nm, 1),
            width_nm       = round(diameter_nm, 1),
            total_score    = round(total, 3),
            vesicle_score  = round(ves_score, 3),
            darkness_score = round(dark, 3),
            shape_score    = 1.0,
            halo_cover     = round(halo_cover, 3),
            cristae_penalty= round(crist_pen, 3),
            angle_deg      = 0.0,
            morphology     = "spherical",
            notes=(
                f"blob σ={sigma_pk:.1f}px d={diameter_nm:.0f}nm "
                f"dark={dark:.2f} ves={ves_score:.2f} "
                f"halo={halo_cover:.2f} size={size_score:.2f}"
            ),
        )
        c._cx_px   = float(cx_i)
        c._cy_px   = float(cy_i)
        c._is_blob = True
        used_centres.append((float(cx_i), float(cy_i)))
        candidates.append(c)

    return candidates


def _classify_morphology(length_nm: float, ratio: float) -> str:
    """GT morphology classification."""
    if ratio < 1.8:
        return "spherical"
    if length_nm > 520.0:
        return "elongated"
    if length_nm < 80.0:
        return "short"
    return "normal"


def _dedup(cands: list[RibbonCandidate], min_dist: float) -> list[RibbonCandidate]:
    kept = []
    for c in cands:
        if not any(math.hypot(c._cx_px - k._cx_px, c._cy_px - k._cy_px) < min_dist
                   for k in kept):
            kept.append(c)
    return kept


def candidates_to_ribbon_data(candidates: list[RibbonCandidate]) -> list[dict]:
    return [{
        "id":              c.id,
        "bbox":            [c.bbox_x, c.bbox_y, c.bbox_w, c.bbox_h],
        "line":            [c.x1_pct, c.y1_pct, c.x2_pct, c.y2_pct],
        "morphology":      c.morphology,
        "confidence":      c.confidence,
        "length_relative": c.bbox_h,
        "width_relative":  c.bbox_w,
        "angle_deg":       c.angle_deg,
        "vesicle_halo":    c.vesicle_score > 0.3,
        "anchored_to_az":  True,
        "inside_spherule": True,
        "notes":           c.notes,
        "_local_score":    c.total_score,
    } for c in candidates]
