"""
Export module: CSV, Excel (with stats), text report
"""

from pathlib import Path
from datetime import datetime
import math
import re
import pandas as pd

from .models import Project


def _fmt(val, decimals=1) -> str:
    """Format a numeric value, returning 'N/A' for NaN/None."""
    try:
        if val is None or math.isnan(float(val)):
            return "N/A"
        return f"{float(val):.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"
from .plots import generate_all_plots


def _csv_literal(value):
    """Keep spreadsheet formula prefixes inert; numeric values stay numeric."""
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    if isinstance(value, str) and value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value


def _sheet_name(value, used):
    name = re.sub(r'[\\/*?:\[\]]', '_', value).strip("'")[:31] or 'Group'
    candidate = name
    suffix = 2
    while candidate.casefold() in used:
        ending = f'_{suffix}'
        candidate = name[:31 - len(ending)] + ending
        suffix += 1
    used.add(candidate.casefold())
    return candidate


def export_csv(project: Project, output_dir: Path) -> Path:
    df = project.to_dataframe()
    path = output_dir / "ribbon_measurements.csv"
    df.apply(lambda column: column.map(_csv_literal)).to_csv(path, index=False)
    img_df = project.images_dataframe()
    img_df.apply(lambda column: column.map(_csv_literal)).to_csv(output_dir / "image_summary.csv", index=False)
    return path


def export_excel(project: Project, output_dir: Path) -> Path:
    path = output_dir / "ribbon_analysis.xlsx"
    df = project.to_dataframe()
    img_df = project.images_dataframe()
    summary = project.summary_stats()

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="All Ribbons", index=False)
        img_df.to_excel(writer, sheet_name="Per Image", index=False)
        if not summary.empty:
            summary.to_excel(writer, sheet_name="Summary Stats", index=False)

        # Names derived from user-supplied labels must be valid and unique.
        used = {name.casefold() for name in writer.book.sheetnames}
        if not df.empty:
            for (age, geno), grp in df.groupby(["age", "genotype"]):
                sheet_name = _sheet_name(f"{age}_{geno}", used)
                grp.to_excel(writer, sheet_name=sheet_name, index=False)

        if not img_df.empty:
            for (age, geno), grp in img_df.groupby(["age", "genotype"]):
                sheet_name = _sheet_name(f"img_{age}_{geno}", used)
                grp.to_excel(writer, sheet_name=sheet_name, index=False)

        # This workbook contains data only, never executable formulas from notes.
        for sheet in writer.book.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type == 'f':
                        cell.data_type = 's'

    return path


def export_text_report(project: Project, output_dir: Path) -> Path:
    path = output_dir / "analysis_report.txt"
    df = project.to_dataframe()
    summary = project.summary_stats()

    lines = [
        "=" * 60,
        "RIBBON SYNAPSE EM ANALYSIS REPORT",
        f"Project: {project.name}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Root folder: {project.root_folder}",
        f"Scale: {project.scale_px} px = {project.scale_nm} {project.scale_unit}",
        "=" * 60,
        "",
        "OVERVIEW",
        "-" * 40,
        f"Total images analyzed: {len(project.image_results)}",
        f"Total ribbons (accepted): {len(df)}",
        f"Total empty terminals: {int(project.images_dataframe()['empty_terminal_count'].sum()) if not project.images_dataframe().empty else 0}",
        f"Timepoints: {sorted(df['age'].unique().tolist()) if not df.empty else []}",
        f"Genotypes: {sorted(df['genotype'].unique().tolist()) if not df.empty else []}",
        "",
    ]

    if not summary.empty:
        lines += ["SUMMARY STATISTICS BY GROUP", "-" * 40]
        for _, row in summary.iterrows():
            n_r = int(row.get("n_ribbons", 0) or 0)
            n_m = int(row.get("n_measured_ribbons", 0) or 0)
            lines += [
                f"\n{row['age']} — {row['genotype']}",
                f"  Ribbons total:   {n_r}  (measured: {n_m}, not measured: {n_r - n_m})",
                f"  Terminals total: {int(row.get('total_terminals', 0) or 0)}  "
                f"(with ribbon: {int(row.get('total_ribbons', n_r) or n_r)}, "
                f"empty: {int(row.get('total_empty_terminals', 0) or 0)})",
                f"  Mean length:     {_fmt(row.get('mean_length_nm'))} ± {_fmt(row.get('std_length_nm'))} nm  (measured only)",
                f"  Median length:   {_fmt(row.get('median_length_nm'))} nm",
                f"  Mean width:      {_fmt(row.get('mean_width_nm'))} nm",
                f"  Normal:          {_fmt(row.get('pct_normal'))}%",
                f"  Elongated:       {_fmt(row.get('pct_elongated'))}%",
                f"  Short:           {_fmt(row.get('pct_short'))}%",
                f"  Detached:        {_fmt(row.get('pct_detached'))}%",
                f"  Empty/img:       {_fmt(row.get('mean_empty_terminals_per_image'))}",
                f"  Terminals/img:   {_fmt(row.get('mean_terminals_per_image'))}",
            ]

    lines += [
        "",
        "IMAGE-BY-IMAGE RESULTS",
        "-" * 40,
    ]
    for ir in project.image_results:
        acc = len([r for r in ir.ribbons if not r.rejected])
        lines.append(
            f"  {ir.image_filename:<40} {ir.age:<6} {ir.genotype:<6} "
            f"{acc} ribbons  empty:{getattr(ir, 'empty_terminal_count', 0)}  quality:{ir.image_quality}"
        )

    if project.literature_notes:
        lines += [
            "",
            "LITERATURE NOTES",
            "-" * 40,
            project.literature_notes,
        ]

    path.write_text("\n".join(lines))
    return path


def export_all(project: Project, output_dir: Path) -> dict:
    """Export everything. Returns dict of {name: path}."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}

    try:
        results["csv"] = export_csv(project, output_dir)
    except Exception as e:
        results["csv_error"] = str(e)

    try:
        results["excel"] = export_excel(project, output_dir)
    except Exception as e:
        results["excel_error"] = str(e)

    try:
        results["report"] = export_text_report(project, output_dir)
    except Exception as e:
        results["report_error"] = str(e)

    try:
        df = project.to_dataframe()
        plots_dir = output_dir / "plots"
        plot_paths = generate_all_plots(df, plots_dir)
        results["plots"] = plot_paths
    except Exception as e:
        results["plots_error"] = str(e)

    return results
