"""GUI regression tests: synthetic files; no network or real research data."""
import tempfile
import os
import socket
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from src.models import Project, ImageResult, RibbonAnnotation
from src.review_panel import ReviewPanel


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.panel = ReviewPanel(self.root)
        self.path = self.directory / 'sample.png'
        Image.new('L', (1000, 500), 160).save(self.path)
        self.ir = ImageResult(str(self.path), self.path.name, 'sample', 'P7', 'WT', analyzed=True,
                              scale_px=100, scale_nm=200)
        self.project = Project('synthetic', str(self.directory), scale_px=100, scale_nm=200,
                               image_results=[self.ir])
        self.panel.load_project(self.project)
        self.training = patch('src.engine.save_training_example')
        self.training.start()

    def tearDown(self):
        self.training.stop()
        self.root.destroy()
        self.tmp.cleanup()

    def draw_axis(self):
        self.panel._start_draw('axis')
        self.panel._draw_pts = [(50, 20), (50, 40)]
        self.panel._finish_draw()

    def test_rectangular_image_uses_actual_vertical_pixels(self):
        self.draw_axis()
        self.assertEqual(self.panel._ribbons[0].length_nm, 200)

    def test_per_image_calibration_and_micrometre_units(self):
        self.ir.scale_px=100; self.ir.scale_nm=0.5; self.ir.scale_unit='µm'
        self.draw_axis()
        self.assertEqual(self.panel._ribbons[0].length_nm, 500)

    def test_curve_width_uses_confirmation_point_without_mouse_motion(self):
        self.panel._start_draw('curve')
        self.panel._draw_pts = [(40, 40), (40, 50)]
        self.panel._finish_curve_draw(42, 45)
        self.assertEqual(self.panel._ribbons[-1].width_nm, 80)

    def test_spherical_radius_uses_vertical_image_dimension(self):
        self.panel._start_draw('spherical')
        self.panel._draw_pts = [(50, 50), (50, 60)]
        self.panel._finish_spherical_draw()
        r = self.panel._ribbons[-1]
        self.assertEqual(r.width_nm, 200)
        self.assertTrue(r.length_not_measured)
        self.assertEqual(r.bbox_h, r.bbox_w * 2)

    def test_invalid_measurement_preserves_annotation(self):
        self.draw_axis()
        before = self.panel._ribbons[0].length_nm
        self.panel.length_var.set('invalid')
        try:
            self.panel._apply_edit()
        except ValueError:
            self.fail('Invalid input must show a recoverable error, not escape the callback')
        self.assertEqual(self.panel._ribbons[0].length_nm, before)

    def test_switching_ribbons_commits_pending_numeric_editor_value(self):
        self.draw_axis(); self.draw_axis()
        self.panel._select_ribbon(0)
        self.panel.length_var.set('333')
        self.panel._request_selection(1)
        self.assertEqual(self.panel._ribbons[0].length_nm, 333)

    def test_invalid_editor_blocks_ribbon_switch_without_discarding_text(self):
        self.draw_axis(); self.draw_axis()
        self.panel._select_ribbon(0)
        self.panel.length_var.set('invalid')
        self.panel._request_selection(1)
        self.assertEqual(self.panel._selected, 0)
        self.assertEqual(self.panel.length_var.get(), 'invalid')

    def test_failed_image_load_clears_old_image(self):
        missing = ImageResult(str(self.directory / 'missing.png'), 'missing.png', 'sample',
                              'P7', 'WT', analyzed=True)
        self.project.image_results.append(missing)
        self.panel.load_project(self.project)
        self.panel._load_image_at(1)
        self.assertIsNone(self.panel._pil_adj)
        self.assertIsNone(self.panel._pil_raw)

    def test_broken_project_shows_error_and_retains_active_annotations(self):
        target = self.directory / 'broken.json'
        target.write_text('{broken')
        self.draw_axis()
        original = self.panel.project
        with patch('src.review_panel.filedialog.askopenfilename', return_value=str(target)), \
             patch.object(self.panel, 'confirm_replace', return_value=True), \
             patch('src.review_panel.messagebox.showerror') as error:
            self.panel._load_project_dialog()
        self.assertTrue(error.called)
        self.assertIs(self.panel.project, original)
        self.assertEqual(len(self.panel._ribbons), 1)

    def test_failed_disk_save_does_not_advance_or_lose_work(self):
        self.project.image_results.append(ImageResult(str(self.path), self.path.name,
            'sample', 'P7', 'WT', analyzed=True))
        self.panel.load_project(self.project)
        self.draw_axis()
        target = self.directory / 'project.json'
        with patch('src.review_panel.filedialog.asksaveasfilename', return_value=str(target)), \
             patch.object(self.project, 'save', side_effect=OSError('simulated disk failure')), \
             patch('src.review_panel.messagebox.showerror') as error:
            self.panel._save_next()
        self.assertTrue(error.called)
        self.assertEqual(self.panel._cur_idx, 0)
        self.assertEqual(len(self.panel._ribbons), 1)
        self.assertTrue(self.panel.has_unsaved_changes())

    def test_invalid_empty_terminal_count_blocks_save(self):
        self.draw_axis()
        for value in ['-1', '1.5', 'nan', 'inf', 'text']:
            self.panel.empty_terminals_var.set(value)
            self.assertFalse(self.panel._save_project())
            self.assertEqual(self.ir.empty_terminal_count, 0)

    def test_cancelled_replacement_keeps_annotation_buffer(self):
        self.draw_axis()
        with patch('src.review_panel.messagebox.askyesnocancel', return_value=None):
            self.assertFalse(self.panel.confirm_replace())
        self.assertEqual(len(self.panel._ribbons), 1)

    def test_editing_notes_does_not_trigger_annotation_shortcuts(self):
        self.draw_axis()
        before = len(self.panel._ribbons)
        self.root.deiconify()
        self.panel.pack(fill='both', expand=True)
        self.root.update()
        self.panel.notes_text.focus_force()
        self.root.update()
        self.panel.notes_text.event_generate('<KeyPress>', keysym='a')
        self.panel.notes_text.event_generate('<KeyPress>', keysym='Delete')
        self.root.update()
        self.assertEqual(len(self.panel._ribbons), before)

    def test_save_and_next_writes_annotations_to_disk(self):
        target = self.directory / 'annotations.json'
        self.draw_axis()
        with patch('src.review_panel.filedialog.asksaveasfilename', return_value=str(target)):
            self.panel._save_project()
        self.panel._ribbons[0].morphology = 'fragmented'
        self.panel.morph_var.set('fragmented')
        self.panel._save_next()
        saved = Project.load(target)
        self.assertEqual(saved.image_results[0].ribbons[0].morphology, 'fragmented')

    def test_each_panel_has_its_own_shortcuts(self):
        other = ReviewPanel(self.root)
        self.assertNotEqual(self.panel.canvas.bindtags(), other.canvas.bindtags())
        # No app-wide bindings: otherwise typing A/R or Delete edits hidden panels.
        self.assertFalse(self.root.bind_all('<a>'))
        self.assertFalse(self.root.bind_all('<Delete>'))

    def test_editor_remains_reachable_in_short_window(self):
        self.root.geometry('1200x700')
        self.panel.pack(fill='both', expand=True)
        self.root.deiconify()
        self.root.update()
        canvas = self.panel._editor_canvas
        self.assertLess(canvas.yview()[1], 1)
        canvas.yview_moveto(1)
        self.root.update()
        self.assertAlmostEqual(canvas.yview()[1], 1)
        button = self.panel._apply_button
        self.assertGreaterEqual(button.winfo_rooty(), canvas.winfo_rooty())
        self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                             canvas.winfo_rooty() + canvas.winfo_height())

    def test_cancelled_save_does_not_advance_image(self):
        self.project.image_results.append(ImageResult(str(self.path), self.path.name,
            'sample', 'P7', 'WT', analyzed=True))
        self.panel.load_project(self.project)
        self.draw_axis()
        with patch('src.review_panel.filedialog.asksaveasfilename', return_value=''):
            self.panel._save_next()
        self.assertEqual(self.panel._cur_idx, 0)
        self.assertEqual(len(self.panel._ribbons), 1)

    def test_zero_ribbon_image_review_is_persisted(self):
        target = self.directory / 'empty.json'
        with patch('src.review_panel.filedialog.asksaveasfilename', return_value=str(target)):
            self.panel._save_next()
        self.assertTrue(Project.load(target).image_results[0].reviewed)

    def test_open_project_prompts_for_missing_images(self):
        target = self.directory / 'moved.json'
        old = Project('moved', '/old/folder', image_results=[ImageResult(
            '/old/folder/sample.png', 'sample.png', 'folder', 'P7', 'WT', analyzed=True)])
        old.save(target)
        self.panel.project = None
        with patch('src.review_panel.filedialog.askopenfilename', return_value=str(target)), \
             patch('src.review_panel.messagebox.askyesno', return_value=True), \
             patch('src.review_panel.filedialog.askdirectory', return_value=str(self.directory)):
            self.panel._load_project_dialog()
        self.assertEqual(Path(self.panel.project.image_results[0].image_path).resolve(), self.path.resolve())
        self.assertTrue(self.panel.has_unsaved_changes())

    def test_merge_morphology_survives_editor_commit(self):
        self.draw_axis()
        self.draw_axis()
        self.panel._select_ribbon(0)
        self.panel._merge_ribbons()
        self.panel._save_current(save_training=False)
        self.assertEqual(self.ir.ribbons[0].morphology, 'fragmented')

    def test_deletion_does_not_apply_previous_editor_to_remaining_ribbon(self):
        self.draw_axis(); self.draw_axis()
        self.panel._select_ribbon(0)
        self.panel.morph_var.set('spherical')
        self.panel._apply_edit()
        self.panel._delete_selected()
        self.panel._save_current(save_training=False)
        self.assertEqual(self.ir.ribbons[0].morphology, 'normal')

    def test_skip_after_save_does_not_retain_new_ribbon_edits(self):
        self.project.image_results.append(ImageResult(str(self.path), self.path.name,
            'sample', 'P7', 'WT', analyzed=True))
        self.panel.load_project(self.project)
        self.draw_axis()
        self.panel._save_current(save_training=False)
        self.panel._ribbons[0].morphology = 'fragmented'
        self.panel._skip()
        self.assertEqual(self.ir.ribbons[0].morphology, 'normal')

class ApplicationTests(unittest.TestCase):
    def setUp(self):
        from src.app import RibbonAnalyzerApp
        self.app = RibbonAnalyzerApp()
        self.app.root.withdraw()
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name) / 'input'
        self.directory.mkdir()

    def tearDown(self):
        self.app.root.destroy()
        self.tmp.cleanup()

    def test_manual_folder_load_is_recursive_and_preserves_group_metadata(self):
        for group in ['P7_WT', 'P10_cKO']:
            path = self.directory / group / 'animal1' / 'sample.tif'
            path.parent.mkdir(parents=True)
            Image.new('L', (80, 60), 160).save(path)
        with patch('src.app.filedialog.askdirectory', return_value=str(self.directory)):
            self.app._manual_load_folder()
        project = self.app.manual_panel.project
        self.assertEqual(len(project.image_results), 2)
        self.assertEqual({(ir.age, ir.genotype) for ir in project.image_results}, {('P7','WT'),('P10','cKO')})
        self.assertTrue(all(ir.analyzed for ir in project.image_results))
        self.assertFalse(self.app.is_analyzing)

    def test_startup_and_manual_use_never_contact_network_even_with_key(self):
        from src.app import RibbonAnalyzerApp
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'not-a-real-key'}), \
             patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')) as connect, \
             patch.object(socket, 'getaddrinfo', side_effect=AssertionError('DNS forbidden')) as dns, \
             patch('src.app.anthropic.Anthropic', side_effect=AssertionError('client forbidden')) as client:
            app = RibbonAnalyzerApp()
            try:
                app.root.withdraw()
                path = self.directory / 'sample.tif'
                Image.new('L', (80,60),160).save(path)
                with patch('src.app.filedialog.askdirectory', return_value=str(self.directory)):
                    app._manual_load_folder()
                target = self.directory / 'annotations.json'
                with patch('src.review_panel.filedialog.asksaveasfilename', return_value=str(target)):
                    self.assertTrue(app.manual_panel._save_project())
                self.assertNotIn('not-a-real-key', target.read_text())
                self.assertFalse(connect.called)
                self.assertFalse(dns.called)
                self.assertFalse(client.called)
            finally:
                app.root.destroy()

    def test_file_open_targets_manual_workspace_and_restores_calibration(self):
        path = self.directory / 'sample.tif'
        Image.new('L', (80,60),160).save(path)
        ir = ImageResult(str(path), path.name, 'input', 'P7', 'WT', analyzed=True,
                         scale_px=100, scale_nm=250)
        project = Project('synthetic', str(self.directory), scale_px=100, scale_nm=250,
                          image_results=[ir])
        target = self.directory / 'project.json'; project.save(target)
        with patch('src.review_panel.filedialog.askopenfilename', return_value=str(target)):
            self.app._open_project()
        self.assertEqual(self.app.manual_panel.project.name, 'synthetic')
        self.assertEqual(self.app.scale_px_var.get(), '100')
        self.assertEqual(self.app.scale_nm_var.get(), '250')
        self.assertEqual(self.app.notebook.select(), str(self.app.manual_frame))
