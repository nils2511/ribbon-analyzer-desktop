"""Create synthetic geometry fixtures. These are not real electron micrographs."""
from pathlib import Path
import argparse
import numpy as np
from PIL import Image, ImageDraw
from src.models import Project, ImageResult, RibbonAnnotation


def create_demo(output_dir: Path) -> Path:
    output_dir = Path(output_dir).resolve()
    folder = output_dir / 'P10_WT'
    folder.mkdir(parents=True, exist_ok=True)
    image_path = folder / 'synthetic_profiles.png'
    project_path = output_dir / 'synthetic_annotations.json'
    # Preserve existing demo annotations when launching the demo again.
    if project_path.exists() and image_path.exists():
        return project_path
    rng = np.random.default_rng(42)
    image = Image.fromarray(np.clip(rng.normal(172, 4, (700, 1000)), 0, 255).astype('uint8'))
    draw = ImageDraw.Draw(image)
    draw.text((24, 20), 'SYNTHETIC GEOMETRY DEMO - NOT EM DATA', fill=40)
    centres = [(250, 320), (550, 320), (790, 320)]
    for cx, cy in centres:
        draw.ellipse((cx-115, cy-160, cx+115, cy+160), outline=95, width=3)
        for angle in np.linspace(0, 2*np.pi, 23, endpoint=False):
            x, y = cx+75*np.cos(angle), cy+112*np.sin(angle)
            draw.ellipse((x-6, y-6, x+6, y+6), outline=105, width=2)
    draw.line((250, 260, 250, 380), fill=45, width=14)
    curve = [(530, 260), (548, 292), (540, 325), (560, 360), (552, 380)]
    draw.line(curve, fill=45, width=14, joint='curve')
    draw.ellipse((765, 295, 815, 345), fill=45)
    draw.line((810, 630, 970, 630), fill=30, width=5)
    draw.text((855, 645), '500 nm', fill=30)
    image.save(image_path)
    ir = ImageResult(str(image_path), image_path.name, folder.name, 'P10', 'WT',
        analyzed=True, scale_px=160, scale_nm=500,
        overall_notes='Synthetic profiles for testing annotation controls only.')
    common = dict(image_path=str(image_path), image_filename=image_path.name,
        folder_name=folder.name, age='P10', genotype='WT', reviewed=True, accepted=True,
        user_edited=True, scale_px=160, scale_nm=500, image_width_px=1000, image_height_px=700,
        notes='Synthetic geometry; no biological interpretation.')
    ir.ribbons = [
        RibbonAnnotation(id=1, bbox_x=25, bbox_y=320/7, bbox_w=1.4, bbox_h=120/7,
            length_nm=375, line_coords=[25, 260/7, 25, 380/7], **common),
        RibbonAnnotation(id=2, bbox_x=54.8, bbox_y=320/7, bbox_w=3, bbox_h=120/7,
            length_nm=round(sum(np.hypot(b[0]-a[0], b[1]-a[1]) for a,b in zip(curve,curve[1:]))*500/160,1),
            polyline_pts=[[x/10, y/7] for x,y in curve], **common),
        RibbonAnnotation(id=3, bbox_x=79, bbox_y=320/7, bbox_w=5, bbox_h=50/7,
            morphology='spherical', length_not_measured=True, width_nm=156.2, **common),
    ]
    Project('Synthetic geometry demo', str(output_dir), scale_px=160, scale_nm=500,
            image_results=[ir]).save(project_path)
    return project_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', nargs='?', type=Path, default=Path('demo_output'))
    print(create_demo(parser.parse_args().output))
