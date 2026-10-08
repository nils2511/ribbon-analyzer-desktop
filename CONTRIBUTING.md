# Contributing

Ribbon Analyzer focuses on manual EM annotation and preserving saved projects. Changes should keep image-folder loading, project saving/reopening and missing-folder relocation working. Automatic detection and vesicle estimates remain experimental.

For bug reports, describe the steps, expected behaviour, actual behaviour, operating system and Python version. Reproduce the issue with the synthetic demo whenever possible. Do not attach API keys, unpublished micrographs, real project JSON files or screenshots containing private paths. Review notes and exports may contain research information too.

For a code change, explain the problem, preserve existing saved measurements and add a regression test when fixing a data-loss or measurement bug. Run:

```bash
python -m unittest discover -s tests -v
python scripts/check_release.py
```

GUI tests require a display; on Linux use `xvfb-run -a`. The release check examines staged files and reachable Git history. Research data, generated outputs and credentials must remain outside the publication allowlist. Discuss major changes to annotation conventions before implementing them.

Report security issues privately as described in [SECURITY.md](SECURITY.md).
