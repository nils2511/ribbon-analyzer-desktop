"""Publication checks must reject private files without exposing their contents."""
import unittest
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch
import scripts.check_release as release
from scripts.check_release import check_files


class ReleaseTests(unittest.TestCase):
    def test_private_data_is_outside_allowlist(self):
        self.assertTrue(check_files([('training_examples.json', b'{}')]))
        self.assertTrue(check_files([('.env', b'placeholder')]))

    def test_credentials_are_flagged_without_values(self):
        secret = 'sk-' + 'a' * 40
        findings = check_files([('src/example.py', secret.encode())])
        self.assertTrue(findings)
        self.assertNotIn(secret, str(findings))

    def test_windows_paths_are_detected_with_single_or_escaped_slashes(self):
        for separator in ('\\', '\\\\'):
            path = separator.join(['C:', 'Users', 'private-user', 'images'])
            self.assertTrue(check_files([('README.md', path.encode())]))

    def test_placeholder_is_allowed(self):
        self.assertFalse(check_files([('README.md', b'Use your own API key: sk-ant-...')]))

    def test_past_secret_is_detected_after_latest_file_is_clean(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            def git(*args):
                subprocess.run(['git', '-c', 'user.name=Test', '-c',
                                'user.email=test@example.invalid', *args],
                               cwd=root, check=True, capture_output=True)
            git('init')
            secret = 'sk-' + 'a' * 40
            path = root / 'README.md'
            path.write_text(secret)
            git('add', 'README.md'); git('commit', '-m', 'Synthetic history fixture')
            path.write_text('plain synthetic text'); git('add', 'README.md')
            count, commits, findings = release.check_repository(root)
            self.assertEqual((count, commits), (1, 1))
            self.assertTrue(findings)
            self.assertIn('commit', str(findings))
            self.assertNotIn(secret, str(findings))

    def test_publication_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            subprocess.run(['git', 'init'], cwd=root, check=True, capture_output=True)
            (root / 'src').mkdir()
            (root / 'private.txt').write_text('synthetic')
            (root / 'src' / 'example.py').symlink_to('../private.txt')
            subprocess.run(['git', 'add', 'src/example.py'], cwd=root, check=True)
            count, commits, findings = release.check_repository(root)
            self.assertTrue(any('symlink' in item for item in findings))


if __name__ == '__main__':
    unittest.main()
