#!/usr/bin/env python3
"""Ribbon Analyzer: local manual annotation and measurement of EM ribbon profiles."""
import argparse
import sys
from pathlib import Path


def main():
    if sys.version_info < (3, 10):
        sys.exit('Python 3.10+ required.')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='Open synthetic annotation examples')
    args = parser.parse_args()
    from src.app import RibbonAnalyzerApp
    app = RibbonAnalyzerApp()
    if args.demo:
        from examples.create_demo import create_demo
        from src.models import Project
        path = create_demo(Path(__file__).resolve().parent / 'demo_output')
        app.manual_panel.load_project(Project.load(path), project_path=path)
        app.manual_panel._status.set('Synthetic geometry demo — not EM data or detector validation.')
    app.run()


if __name__ == '__main__':
    main()
