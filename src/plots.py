"""
Statistics and visualization for ribbon analysis results.
Generates matplotlib figures for:
- Length distributions per age/genotype
- Morphology breakdown
- WT vs cKO comparison
- Developmental trajectory
"""

import matplotlib
# Batch exports also run without a display (e.g. CI).
import os
import sys
matplotlib.use("TkAgg" if sys.platform in ("darwin", "win32") or os.environ.get("DISPLAY") else "Agg")

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from typing import Optional
from pathlib import Path

from .config import MORPHOLOGY_COLORS, MORPHOLOGY_CLASSES

# Clean plot style
plt.rcParams.update({
    "figure.facecolor": "#121a20",
    "axes.facecolor": "#10171d",
    "axes.edgecolor": "#354550",
    "axes.labelcolor": "#aaaaaa",
    "xtick.color": "#a9b9c6",
    "ytick.color": "#a9b9c6",
    "text.color": "#e0e0e0",
    "grid.color": "#1e1e3a",
    "grid.alpha": 0.5,
    "font.family": "sans-serif",
    "axes.titlecolor": "#e0e0e0",
    "axes.titlesize": 11,
    "axes.labelsize": 9,
})

WT_COLOR = "#378ADD"
CKO_COLOR = "#D85A30"
GENOTYPE_COLORS = {"WT": WT_COLOR, "cKO": CKO_COLOR}


def plot_length_distributions(df: pd.DataFrame, save_path: Optional[Path] = None):
    """Violin/box plots of ribbon lengths by age and genotype."""
    if df.empty:
        return None

    ages = sorted(df["age"].unique(), key=lambda x: int(x[1:]) if x[1:].isdigit() else 99)
    genotypes = [g for g in ["WT", "cKO"] if g in df["genotype"].unique()]

    fig, axes = plt.subplots(1, len(ages), figsize=(4 * len(ages), 5),
                              sharey=True, facecolor="#121a20")
    if len(ages) == 1:
        axes = [axes]

    fig.suptitle("Ribbon Length Distribution — WT vs cKO", fontsize=13, y=1.02, color="#e0e0e0")

    for ax, age in zip(axes, ages):
        age_df = df[df["age"] == age]
        positions = []
        data_to_plot = []
        colors = []
        labels = []
        for j, geno in enumerate(genotypes):
            sub = age_df[age_df["genotype"] == geno]["length_nm"].dropna()
            if len(sub) > 0:
                positions.append(j + 1)
                data_to_plot.append(sub.values)
                colors.append(GENOTYPE_COLORS.get(geno, "#a9b9c6"))
                labels.append(geno)

        if data_to_plot:
            vp = ax.violinplot(data_to_plot, positions=positions,
                               showmedians=True, showextrema=True)
            for i, (body, col) in enumerate(zip(vp["bodies"], colors)):
                body.set_facecolor(col)
                body.set_alpha(0.7)
                body.set_edgecolor("#ffffff")
                body.set_linewidth(0.5)
            vp["cmedians"].set_color("#ffffff")
            vp["cmedians"].set_linewidth(2)
            vp["cmaxes"].set_color("#555555")
            vp["cmins"].set_color("#555555")
            vp["cbars"].set_color("#555555")

            # Overlay scatter
            for i, (d, pos, col) in enumerate(zip(data_to_plot, positions, colors)):
                jitter = np.random.normal(0, 0.05, size=len(d))
                ax.scatter(pos + jitter, d, c=col, alpha=0.4, s=8, zorder=5)

        ax.set_title(age, fontsize=11)
        ax.set_xticks(positions)
        ax.set_xticklabels(labels)
        ax.set_xlabel("")
        ax.grid(axis="y", alpha=0.3)
        ax.axhline(y=300, color="#a9b9c6", linewidth=0.5, linestyle="--", alpha=0.5,
                   label="~300nm (reference)")

    axes[0].set_ylabel("Ribbon length (nm)")
    legend_patches = [Patch(facecolor=GENOTYPE_COLORS.get(g, "#888"), label=g) for g in genotypes]
    fig.legend(handles=legend_patches, loc="upper right", framealpha=0.2,
               facecolor="#10171d", edgecolor="#354550")
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="#121a20")
    return fig


def plot_morphology_breakdown(df: pd.DataFrame, save_path: Optional[Path] = None):
    """Stacked bar chart of morphology distribution per group."""
    if df.empty:
        return None

    groups = df.groupby(["age", "genotype"])["morphology"].value_counts(normalize=True).unstack(fill_value=0) * 100
    groups = groups.reset_index()
    groups["group"] = groups["age"] + "\n" + groups["genotype"]

    fig, ax = plt.subplots(figsize=(max(6, len(groups) * 1.2), 5), facecolor="#121a20")
    fig.suptitle("Ribbon Morphology Breakdown", fontsize=13, color="#e0e0e0")

    morphs = [m for m in MORPHOLOGY_CLASSES
              if m in groups.columns]
    x = np.arange(len(groups))
    bottom = np.zeros(len(groups))

    for m in morphs:
        vals = groups[m].values if m in groups.columns else np.zeros(len(groups))
        col = MORPHOLOGY_COLORS.get(m, "#a9b9c6")
        ax.bar(x, vals, bottom=bottom, label=m.capitalize(), color=col, alpha=0.85, width=0.6)
        bottom += vals

    ax.set_xticks(x)
    ax.set_xticklabels(groups["group"].values, fontsize=9)
    ax.set_ylabel("Percentage (%)")
    ax.set_ylim(0, 105)
    ax.legend(loc="upper right", framealpha=0.2, facecolor="#10171d",
              edgecolor="#354550", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="#121a20")
    return fig


def plot_developmental_trajectory(df: pd.DataFrame, save_path: Optional[Path] = None):
    """Line plot of mean ribbon length across developmental ages for WT vs cKO."""
    if df.empty:
        return None

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5), facecolor="#121a20")
    fig.suptitle("Developmental Trajectory of Synaptic Ribbons", fontsize=13, color="#e0e0e0")

    age_order = sorted((a for a in df["age"].unique() if a.startswith("P") and a[1:].isdigit()), key=lambda a: int(a[1:]))
    ages_present = [a for a in age_order if a in df["age"].unique()]
    age_nums = [int(a[1:]) for a in ages_present]

    for geno, col in GENOTYPE_COLORS.items():
        sub = df[df["genotype"] == geno]
        if sub.empty:
            continue
        means, sems, ages_used, nums_used = [], [], [], []
        for age, num in zip(ages_present, age_nums):
            g = sub[sub["age"] == age]["length_nm"].dropna()
            if len(g) > 0:
                means.append(g.mean())
                sems.append(g.sem() if len(g) > 1 else 0.0)
                ages_used.append(age)
                nums_used.append(num)
        if means:
            ax1.plot(nums_used, means, "o-", color=col, label=geno, linewidth=2, markersize=6)
            ax1.fill_between(nums_used,
                             [m - s for m, s in zip(means, sems)],
                             [m + s for m, s in zip(means, sems)],
                             alpha=0.2, color=col)

    ax1.set_xlabel("Postnatal day")
    ax1.set_ylabel("Mean ribbon length (nm)")
    ax1.set_title("Ribbon length over development")
    if ax1.lines:
        ax1.legend(framealpha=0.2, facecolor="#10171d", edgecolor="#354550")
    ax1.grid(alpha=0.3)
    if age_nums:
        ax1.set_xticks(age_nums)
        ax1.set_xticklabels(ages_present)

    # Ribbon count per image
    counts = df.groupby(["age", "genotype"]).size().reset_index(name="count")
    for geno, col in GENOTYPE_COLORS.items():
        sub = counts[(counts["genotype"] == geno) & counts["age"].isin(ages_present)]
        sub_ages = [int(a[1:]) for a in sub["age"]]
        if len(sub_ages) > 0:
            ax2.plot(sub_ages, sub["count"].values, "s--", color=col,
                     label=geno, linewidth=1.5, markersize=5, alpha=0.7)

    ax2.set_xlabel("Postnatal day")
    ax2.set_ylabel("Ribbon count")
    ax2.set_title("Total ribbons measured per group")
    if ax2.lines:
        ax2.legend(framealpha=0.2, facecolor="#10171d", edgecolor="#354550")
    ax2.grid(alpha=0.3)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor="#121a20")
    return fig


def generate_all_plots(df: pd.DataFrame, output_dir: Path) -> list[Path]:
    """Generate and save all plots. Returns list of saved paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    funcs = [
        (plot_length_distributions, "length_distributions.png"),
        (plot_morphology_breakdown, "morphology_breakdown.png"),
        (plot_developmental_trajectory, "developmental_trajectory.png"),
    ]
    for func, filename in funcs:
        try:
            p = output_dir / filename
            fig = func(df, save_path=p)
            if fig:
                plt.close(fig)
                saved.append(p)
        except Exception as e:
            print(f"Plot error ({filename}): {e}")
    return saved
