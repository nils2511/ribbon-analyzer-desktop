#!/usr/bin/env python3
"""
Evaluate local_detector.py against manual annotations.
Usage:  python evaluate_detector.py ANNOTATION_FOLDER [--dataset NAME] [--max-images N]

Reports recall/precision per morphology class and overall.
A detected candidate counts as a hit if its centre falls within
max(bbox_w, bbox_h)/2 of any GT ribbon centre.
"""

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict

# ── Setup path ────────────────────────────────────────────────────────────────
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from src.local_detector import detect_ribbons




def load_gt(ann_file: Path) -> dict[str, list[dict]]:
    """Returns {image_path: [ribbon_dict, ...]} for accepted ribbons."""
    data = json.loads(ann_file.read_text())
    result = {}
    for img_data in data.get("image_results", []):
        ribbons = [
            r for r in img_data.get("ribbons", [])
            if r.get("accepted", True) and not r.get("rejected", False)
        ]
        result[img_data["image_path"]] = {
            "ribbons": ribbons,
            "scale_px": data.get("scale_px", 319.0),
            "scale_nm": data.get("scale_nm", 500.0),
        }
    return result


def ribbon_centre_pct(r: dict) -> tuple[float, float]:
    """GT ribbon centre in % coordinates."""
    lc = r.get("line_coords", [])
    if len(lc) == 4:
        return ((lc[0] + lc[2]) / 2.0, (lc[1] + lc[3]) / 2.0)
    return (r.get("bbox_x", 50.0), r.get("bbox_y", 50.0))


def evaluate_image(image_path: Path, gt_ribbons: list[dict],
                   scale_px: float, scale_nm: float) -> dict:
    """Run detector and compare to GT. Returns per-image stats."""
    try:
        from PIL import Image
        im = Image.open(image_path)
        iw, ih = im.size
    except Exception as e:
        return {"error": str(e)}

    # Detect
    try:
        candidates = detect_ribbons(image_path, scale_px=scale_px, scale_nm=scale_nm)
    except Exception as e:
        return {"error": str(e)}

    # Match GT → detection (tolerance = ~half the GT bbox, min 3%)
    gt_matched   = [False] * len(gt_ribbons)
    det_matched  = [False] * len(candidates)

    for gi, gt in enumerate(gt_ribbons):
        gcx, gcy = ribbon_centre_pct(gt)
        gbw = max(gt.get("bbox_w", 3.0), 2.0)
        gbh = max(gt.get("bbox_h", 3.0), 2.0)
        # Match if detected centre is within the GT bounding box
        # (ribbons can be detected at endpoints, not just centroid)
        half_w = gbw / 2.0 + 2.0   # +2% padding
        half_h = gbh / 2.0 + 2.0

        for di, det in enumerate(candidates):
            if det_matched[di]:
                continue
            dcx = det.cx_pct
            dcy = det.cy_pct
            in_bbox = (abs(dcx - gcx) <= half_w and abs(dcy - gcy) <= half_h)
            dist_ok = ((gcx - dcx) ** 2 + (gcy - dcy) ** 2) ** 0.5 <= max(gbh, gbw) / 2
            if in_bbox or dist_ok:
                gt_matched[gi]  = True
                det_matched[di] = True
                break

    tp = sum(gt_matched)
    fn = len(gt_ribbons) - tp
    fp = sum(1 for m in det_matched if not m)

    return {
        "n_gt":       len(gt_ribbons),
        "n_det":      len(candidates),
        "tp":         tp,
        "fn":         fn,
        "fp":         fp,
        "gt_morphs":  [r.get("morphology", "normal") for r in gt_ribbons],
        "tp_morphs":  [gt_ribbons[i].get("morphology", "normal") for i, m in enumerate(gt_matched) if m],
        "fn_morphs":  [gt_ribbons[i].get("morphology", "normal") for i, m in enumerate(gt_matched) if not m],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("annotation_folder", type=Path, help="Folder containing project JSON files")
    parser.add_argument("--dataset", default=None, help="Filter by dataset name substring")
    parser.add_argument("--max-images", type=int, default=None)
    args = parser.parse_args()

    ann_files = sorted(args.annotation_folder.glob("*.json"))
    if args.dataset:
        ann_files = [f for f in ann_files if args.dataset.lower() in f.stem.lower()]

    if not ann_files:
        print("No annotation files found.")
        return

    totals = defaultdict(int)
    morph_tp = defaultdict(int)
    morph_fn = defaultdict(int)
    errors   = 0
    images_processed = 0

    for ann_file in ann_files:
        print(f"\n── {ann_file.stem} ──")
        gt_map = load_gt(ann_file)

        img_count = 0
        for img_path_str, img_info in gt_map.items():
            if args.max_images and img_count >= args.max_images:
                break
            img_path = Path(img_path_str)
            if not img_path.exists():
                continue

            result = evaluate_image(
                img_path, img_info["ribbons"],
                img_info["scale_px"], img_info["scale_nm"]
            )

            if "error" in result:
                errors += 1
                continue

            totals["n_gt"]  += result["n_gt"]
            totals["n_det"] += result["n_det"]
            totals["tp"]    += result["tp"]
            totals["fn"]    += result["fn"]
            totals["fp"]    += result["fp"]

            for m in result["tp_morphs"]:
                morph_tp[m] += 1
            for m in result["fn_morphs"]:
                morph_fn[m] += 1

            img_count += 1
            images_processed += 1

            if img_count % 20 == 0:
                print(f"  {img_count} images...", end="\r")

        print(f"  processed {img_count} images")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "═" * 55)
    print("EVALUATION SUMMARY")
    print("═" * 55)
    tp = totals["tp"]
    fn = totals["fn"]
    fp = totals["fp"]
    n_gt = totals["n_gt"]
    n_det = totals["n_det"]

    recall    = tp / max(tp + fn, 1)
    precision = tp / max(tp + fp, 1)
    f1        = 2 * recall * precision / max(recall + precision, 1e-6)

    print(f"Ground truth ribbons : {n_gt}")
    print(f"Detections           : {n_det}")
    print(f"True positives       : {tp}")
    print(f"False negatives      : {fn}  (missed GT ribbons)")
    print(f"False positives      : {fp}  (spurious detections)")
    print(f"Recall               : {recall:.1%}")
    print(f"Precision            : {precision:.1%}")
    print(f"F1 score             : {f1:.3f}")
    if errors:
        print(f"Errors               : {errors}")

    print("\nPER-MORPHOLOGY RECALL:")
    all_morphs = sorted(set(list(morph_tp.keys()) + list(morph_fn.keys())))
    for m in all_morphs:
        tp_m = morph_tp[m]
        fn_m = morph_fn[m]
        total_m = tp_m + fn_m
        rec_m = tp_m / max(total_m, 1)
        print(f"  {m:12s}: {tp_m:3d}/{total_m:3d} = {rec_m:.1%}")


if __name__ == "__main__":
    main()
