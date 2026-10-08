"""
Data models for ribbon analysis results
"""

import json
import math
import csv
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional
from datetime import datetime

import pandas as pd


@dataclass
class RibbonAnnotation:
    """Single ribbon annotation (one ribbon in one image)."""
    id: int
    image_path: str
    image_filename: str
    folder_name: str
    age: str
    genotype: str

    # Bounding box (percent of image)
    bbox_x: float = 0.0
    bbox_y: float = 0.0
    bbox_w: float = 5.0
    bbox_h: float = 5.0

    # Measurements (None = not measured)
    length_nm: Optional[float] = None
    width_nm: Optional[float] = None
    length_relative: float = 0.0
    width_relative: float = 0.0
    angle_deg: float = 0.0

    # Morphology
    morphology: str = "normal"
    confidence: str = "medium"
    vesicle_halo: bool = False
    anchored_to_az: bool = True
    inside_spherule: bool = True
    notes: str = ""

    # Review
    reviewed: bool = False
    user_edited: bool = False
    accepted: bool = False
    rejected: bool = False
    rejection_reason: str = ""

    # Scale
    scale_px: float = 319.0
    scale_nm: float = 500.0
    scale_unit: str = "nm"

    # Measurement flags
    length_not_measured: bool = False   # ribbon visible but height not measured

    # Vesicle context
    vesicle_count: int = 0
    vesicle_shell_nm: float = 50.0

    # Image size
    image_width_px: int = 0
    image_height_px: int = 0

    # Geometry for manual/review workflows. Keeping these in the dataclass
    # preserves them across Project.save()/load() instead of losing them as
    # ad-hoc attributes.
    line_coords: list[float] = field(default_factory=list)
    polyline_pts: list[list[float]] = field(default_factory=list)


@dataclass
class ImageResult:
    """All ribbons detected in a single image."""
    image_path: str
    image_filename: str
    folder_name: str
    age: str
    genotype: str
    ribbons: list[RibbonAnnotation] = field(default_factory=list)
    empty_terminal_count: int = 0
    image_quality: str = "good"
    developmental_stage_hint: str = ""
    genotype_hint: str = "unclear"
    overall_notes: str = ""
    magnification_estimate: str = ""
    analyzed: bool = False
    reviewed: bool = False
    error: Optional[str] = None
    scale_px: float = 319.0
    scale_nm: float = 500.0
    scale_unit: str = "nm"

    def ribbon_count(self) -> int:
        return len(self.ribbons)

    def accepted_ribbons(self) -> list[RibbonAnnotation]:
        return [r for r in self.ribbons if not r.rejected]


@dataclass
class Project:
    """Top-level project containing all image results."""
    name: str
    root_folder: str
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    scale_px: float = 319.0
    scale_nm: float = 500.0
    scale_unit: str = "nm"
    image_results: list[ImageResult] = field(default_factory=list)
    literature_notes: str = ""

    def save(self, path: Path):
        """Replace only after a complete write; a failed save keeps the old file."""
        path = Path(path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                             dir=path.parent, prefix=f".{path.name}.",
                                             suffix=".tmp", delete=False) as f:
                temporary = Path(f.name)
                json.dump(asdict(self), f, indent=2, ensure_ascii=False, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def relocate_images(self, new_root: Path) -> tuple[int, int]:
        """Restore moved image paths without guessing among duplicate filenames."""
        new_root = Path(new_root).resolve()
        def portable_path(value):
            return PureWindowsPath(value) if "\\" in value else PurePosixPath(value)
        old_root = portable_path(self.root_folder)
        found = missing = 0
        for ir in self.image_results:
            current = Path(ir.image_path)
            target = current if current.is_file() else None
            if target is None:
                candidates = []
                try:
                    relative = portable_path(ir.image_path).relative_to(old_root)
                    if ".." not in relative.parts:
                        candidates.append(new_root.joinpath(*relative.parts))
                except ValueError:
                    pass
                candidates.extend([new_root / ir.folder_name / ir.image_filename,
                                   new_root / ir.image_filename])
                for candidate in candidates:
                    if candidate.is_file() and candidate.resolve().is_relative_to(new_root):
                        target = candidate
                        break
                if target is None:
                    hits = [p for p in new_root.rglob("*")
                            if p.name == ir.image_filename and p.is_file()
                            and p.resolve().is_relative_to(new_root)]
                    if len(hits) == 1:
                        target = hits[0]
            if target is None:
                missing += 1
                continue
            ir.image_path = str(target)
            for r in ir.ribbons:
                r.image_path = str(target)
            found += 1
        if found:
            self.root_folder = str(new_root)
        return found, missing

    @classmethod
    def load(cls, path: Path) -> "Project":
        def reject_constant(value):
            raise ValueError("Project contains a non-finite number.")
        with open(path, encoding="utf-8") as f:
            data = json.load(f, parse_constant=reject_constant)
        if not isinstance(data, dict) or not isinstance(data.get("image_results", []), list):
            raise ValueError("Project must contain an object and a list of image results.")
        project = cls(
            name=data["name"],
            root_folder=data["root_folder"],
            created=data.get("created", ""),
            scale_px=data.get("scale_px", 319.0),
            scale_nm=data.get("scale_nm", 500.0),
            scale_unit=data.get("scale_unit", "nm"),
            literature_notes=data.get("literature_notes", ""),
        )
        for ir_data in data.get("image_results", []):
            if not isinstance(ir_data, dict) or not isinstance(ir_data.get("ribbons", []), list):
                raise ValueError("Each image must contain an object and a list of ribbons.")
            ir = ImageResult(
                image_path=ir_data["image_path"],
                image_filename=ir_data["image_filename"],
                folder_name=ir_data["folder_name"],
                age=ir_data["age"],
                genotype=ir_data["genotype"],
                empty_terminal_count=ir_data.get("empty_terminal_count", 0),
                image_quality=ir_data.get("image_quality", "good"),
                developmental_stage_hint=ir_data.get("developmental_stage_hint", ""),
                genotype_hint=ir_data.get("genotype_hint", "unclear"),
                overall_notes=ir_data.get("overall_notes", ""),
                magnification_estimate=ir_data.get("magnification_estimate", ""),
                analyzed=ir_data.get("analyzed", False),
                reviewed=ir_data.get("reviewed", False),
                error=ir_data.get("error"),
                scale_px=ir_data.get("scale_px", 319.0),
                scale_nm=ir_data.get("scale_nm", 500.0),
                scale_unit=ir_data.get("scale_unit", "nm"),
            )
            for r_data in ir_data.get("ribbons", []):
                if not isinstance(r_data, dict):
                    raise ValueError("Each ribbon must be an object.")
                r = RibbonAnnotation(**{k: v for k, v in r_data.items() if k in RibbonAnnotation.__dataclass_fields__})
                ir.ribbons.append(r)
            project.image_results.append(ir)
        project._validate_loaded()
        return project

    def _validate_loaded(self):
        """Reject unusable input before replacing the currently open project."""
        def numeric(value, name, positive=False, whole=False, nonnegative=True):
            try:
                valid = (type(value) in (int, float) and math.isfinite(value)
                         and (not positive or value > 0)
                         and (not nonnegative or value >= 0)
                         and (not whole or float(value).is_integer()))
            except (ValueError, OverflowError):
                valid = False
            if not valid:
                raise ValueError(f"Invalid numeric field: {name}.")

        def text_fields(obj, names):
            for name in names:
                if not isinstance(getattr(obj, name), str):
                    raise ValueError(f"Invalid text field: {name}.")

        def calibration(obj):
            numeric(obj.scale_px, "scale_px", positive=True)
            numeric(obj.scale_nm, "scale_nm", positive=True)
            if obj.scale_unit not in ("nm", "µm", "um", "μm"):
                raise ValueError("Unsupported scale unit.")

        text_fields(self, ("name", "root_folder", "created", "literature_notes"))
        calibration(self)
        for image in self.image_results:
            calibration(image)
            text_fields(image, ("image_path", "image_filename", "folder_name", "age", "genotype",
                                "image_quality", "developmental_stage_hint", "genotype_hint",
                                "overall_notes", "magnification_estimate"))
            numeric(image.empty_terminal_count, "empty_terminal_count", whole=True)
            for ribbon in image.ribbons:
                calibration(ribbon)
                text_fields(ribbon, ("image_path", "image_filename", "folder_name", "age", "genotype",
                                     "morphology", "confidence", "notes", "rejection_reason"))
                for name in ("bbox_x", "bbox_y", "bbox_w", "bbox_h", "length_relative",
                             "width_relative", "angle_deg"):
                    numeric(getattr(ribbon, name), name, nonnegative=False)
                for name in ("length_nm", "width_nm"):
                    if getattr(ribbon, name) is not None:
                        numeric(getattr(ribbon, name), name)
                for name in ("id", "vesicle_count", "image_width_px", "image_height_px"):
                    numeric(getattr(ribbon, name), name, whole=True)
                numeric(ribbon.vesicle_shell_nm, "vesicle_shell_nm")
                line = ribbon.line_coords
                if not isinstance(line, list) or (line and (len(line) < 4 or len(line) % 2)):
                    raise ValueError("Invalid straight-axis geometry.")
                for value in line:
                    numeric(value, "line_coords", nonnegative=False)
                if not isinstance(ribbon.polyline_pts, list):
                    raise ValueError("Invalid curved-axis geometry.")
                for point in ribbon.polyline_pts:
                    if not isinstance(point, list) or len(point) != 2:
                        raise ValueError("Invalid curved-axis point.")
                    for value in point:
                        numeric(value, "polyline_pts", nonnegative=False)

    def to_dataframe(self) -> pd.DataFrame:
        rows = []
        for ir in self.image_results:
            for r in ir.accepted_ribbons():
                rows.append({
                    "image_filename": r.image_filename,
                    "folder": r.folder_name,
                    "age": r.age,
                    "genotype": r.genotype,
                    "ribbon_id": r.id,
                    "measured": r.length_nm is not None,
                    "length_nm": r.length_nm,
                    "width_nm": r.width_nm,
                    "morphology": r.morphology,
                    "confidence": r.confidence,
                    "vesicle_halo": r.vesicle_halo,
                    "anchored_to_az": r.anchored_to_az,
                    "inside_spherule": r.inside_spherule,
                    "notes": r.notes,
                    "reviewed": r.reviewed,
                    "user_edited": r.user_edited,
                    "image_quality": ir.image_quality,
                    "developmental_stage_hint": ir.developmental_stage_hint,
                    "empty_terminal_count": ir.empty_terminal_count,
                })
        return pd.DataFrame(rows)

    def images_dataframe(self) -> pd.DataFrame:
        rows = []
        for ir in self.image_results:
            accepted = ir.accepted_ribbons()
            ribbon_count = len(accepted)
            rows.append({
                "image_filename": ir.image_filename,
                "folder": ir.folder_name,
                "age": ir.age,
                "genotype": ir.genotype,
                "analyzed": ir.analyzed,
                "image_quality": ir.image_quality,
                "ribbon_count": ribbon_count,
                "measured_ribbon_count": sum(1 for r in accepted if r.length_nm is not None),
                "empty_terminal_count": ir.empty_terminal_count,
                "total_terminal_count": ribbon_count + ir.empty_terminal_count,
                "overall_notes": ir.overall_notes,
                "developmental_stage_hint": ir.developmental_stage_hint,
                "genotype_hint": ir.genotype_hint,
            })
        return pd.DataFrame(rows)

    def summary_stats(self) -> pd.DataFrame:
        df = self.to_dataframe()
        img_df = self.images_dataframe()
        if df.empty and img_df.empty:
            return pd.DataFrame()
        if df.empty:
            grouped = img_df.groupby(["age", "genotype"]).agg(
                n_images=("image_filename", "count"),
                total_ribbons=("ribbon_count", "sum"),
                total_empty_terminals=("empty_terminal_count", "sum"),
                total_terminals=("total_terminal_count", "sum"),
                mean_empty_terminals_per_image=("empty_terminal_count", "mean"),
                mean_terminals_per_image=("total_terminal_count", "mean"),
            ).round(1).reset_index()
            grouped["n_ribbons"] = 0
            grouped["n_measured_ribbons"] = 0
            grouped["mean_length_nm"] = float("nan")
            grouped["std_length_nm"] = float("nan")
            grouped["median_length_nm"] = float("nan")
            grouped["mean_width_nm"] = float("nan")
            grouped["pct_normal"] = 0.0
            grouped["pct_elongated"] = 0.0
            grouped["pct_short"] = 0.0
            grouped["pct_detached"] = 0.0
            return grouped

        ribbon_grouped = df.groupby(["age", "genotype"]).agg(
            n_ribbons=("ribbon_id", "count"),
            n_measured_ribbons=("measured", "sum"),
            mean_length_nm=("length_nm", "mean"),
            std_length_nm=("length_nm", "std"),
            median_length_nm=("length_nm", "median"),
            mean_width_nm=("width_nm", "mean"),
            pct_normal=("morphology", lambda x: (x == "normal").mean() * 100),
            pct_elongated=("morphology", lambda x: (x == "elongated").mean() * 100),
            pct_short=("morphology", lambda x: (x == "short").mean() * 100),
            pct_detached=("morphology", lambda x: (x == "detached").mean() * 100),
        )
        image_grouped = img_df.groupby(["age", "genotype"]).agg(
            n_images=("image_filename", "count"),
            total_ribbons=("ribbon_count", "sum"),
            total_empty_terminals=("empty_terminal_count", "sum"),
            total_terminals=("total_terminal_count", "sum"),
            mean_empty_terminals_per_image=("empty_terminal_count", "mean"),
            mean_terminals_per_image=("total_terminal_count", "mean"),
        )
        grouped = ribbon_grouped.join(image_grouped, how="outer").round(1).reset_index()
        grouped[["n_ribbons", "n_measured_ribbons"]] = grouped[["n_ribbons", "n_measured_ribbons"]].fillna(0)
        return grouped
