"""Regression tests use synthetic images and annotations only."""
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from src.models import Project, ImageResult, RibbonAnnotation
from src.review_panel import ReviewPanel


def image_result(path, folder='sample', **kwargs):
    return ImageResult(str(path), Path(str(path).replace('\\', '/')).name,
                       folder, 'P7', 'WT', **kwargs)


def ribbon(path, **kwargs):
    return RibbonAnnotation(1, str(path), Path(path).name, 'sample', 'P7', 'WT', **kwargs)


class PersistenceTests(unittest.TestCase):
    def test_geometry_and_unmeasured_ribbons_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'project.json'
            ir = image_result(Path(d) / 'image.tif', analyzed=True, empty_terminal_count=2)
            ir.ribbons = [ribbon(Path(ir.image_path), length_nm=None,
                                 length_not_measured=True, morphology='spherical',
                                 line_coords=[10, 20, 30, 40],
                                 polyline_pts=[[10, 20], [30, 40]], notes='µm test')]
            project = Project('sample', d, image_results=[ir])
            project.save(path)
            self.assertEqual(asdict(Project.load(path)), asdict(project))

    def test_failed_save_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'project.json'
            project = Project('sample', d)
            project.save(path)
            previous = path.read_bytes()
            def interrupted_dump(data, file, **kwargs):
                file.write('{broken')
                raise OSError('simulated interruption')
            with patch('src.models.json.dump', interrupted_dump):
                with self.assertRaises(OSError):
                    project.save(path)
            self.assertEqual(path.read_bytes(), previous)

    def test_relocation_preserves_nested_folders_and_ribbon_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            for group in ['WT', 'cKO']:
                p = root / group / 'animal1' / 'image.tif'
                p.parent.mkdir(parents=True); p.write_bytes(b'synthetic')
            project = Project('sample', 'Z:\\old')
            for group in ['WT', 'cKO']:
                ir = image_result(f'Z:\\old\\{group}\\animal1\\image.tif', 'animal1')
                ir.ribbons = [ribbon(Path('image.tif'), length_nm=200)]
                project.image_results.append(ir)
            self.assertEqual(ReviewPanel._remap_project_paths(project, root), (2, 0))
            for group, ir in zip(['WT', 'cKO'], project.image_results):
                self.assertEqual(Path(ir.image_path), root / group / 'animal1' / 'image.tif')
                self.assertEqual(ir.ribbons[0].image_path, ir.image_path)

    def test_relocation_does_not_guess_duplicate_filenames(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            for group in ['first', 'second']:
                p = root / group / 'image.tif'
                p.parent.mkdir(); p.write_bytes(b'synthetic')
            ir = image_result('/missing/unrelated/image.tif', 'unrelated')
            project = Project('sample', '/missing', image_results=[ir])
            self.assertEqual(ReviewPanel._remap_project_paths(project, root), (0, 1))
            self.assertEqual(ir.image_path, '/missing/unrelated/image.tif')

    def test_export_mixed_groups_with_no_ribbons(self):
        from src.export_module import export_all
        with tempfile.TemporaryDirectory() as d:
            one = image_result(Path(d) / 'one.tif', analyzed=True)
            one.ribbons = [ribbon(Path(one.image_path), length_nm=250)]
            empty = image_result(Path(d) / 'empty.tif', analyzed=True, empty_terminal_count=3)
            empty.age = '12w'; empty.genotype = 'cKO'
            result = export_all(Project('sample', d, image_results=[one, empty]), Path(d) / 'export')
            self.assertFalse([k for k in result if 'error' in k], result)
            self.assertTrue(result['report'].is_file())
            self.assertEqual(len(result['plots']), 3)

    def test_morphology_plot_includes_spherical_ribbons(self):
        from src.plots import plot_morphology_breakdown
        import matplotlib.pyplot as plt
        ir = image_result('sample.tif', analyzed=True)
        ir.ribbons = [ribbon(Path(ir.image_path), morphology='spherical')]
        fig = plot_morphology_breakdown(Project('sample', '.', image_results=[ir]).to_dataframe())
        self.assertIn('Spherical', fig.axes[0].get_legend_handles_labels()[1])
        plt.close(fig)


if __name__ == '__main__':
    unittest.main()
