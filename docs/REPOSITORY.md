# Repository preparation

Reviewed against official GitHub documentation on 8 October 2026. These are choices for this small research tool, rather than a requirement to implement every community feature before publication.

| Area | What belongs here | Current status |
| --- | --- | --- |
| First impression | Clear purpose, manual workflow, screenshot and honest limitations | README and synthetic screenshot included |
| Getting started | Installation, supported Python version, key-free demo and usage guide | Included; Windows scripts still need a Windows run |
| Reuse | Explicit licence chosen by the author | Pending; do not describe the project as open source until selected |
| Attribution | Author and software citation metadata | CITATION.cff includes author and repository URL |
| Contributions | Reproduction steps, tests and expectations about preserving saved projects | CONTRIBUTING.md included |
| Confidentiality | Research data, exports, local paths, credentials and local assistant settings outside the public files | Explicit Git allowlist, index/history check and clean public archive |
| Vulnerability handling | Private reports and dependency alerts | SECURITY.md and Dependabot configuration included; repository settings must be checked after creation |
| Automation | Tests on pushes/PRs, minimal token permissions and fixed Action versions | Workflow included; the repository's Actions tab shows the current result |
| Presentation | Short repository description and relevant topics | Set after the repository destination is known |

GitHub recommends a README explaining the purpose, usefulness, setup, help and maintainership. It also recommends accompanying licence, citation and contribution files. The existing documentation addresses those points, with the licence deliberately left to the author. [Repository best practices](https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories), [README guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes).

For security, check Dependabot alerts, secret scanning, push protection and code scanning in the repository settings. Enable private vulnerability reporting. Those settings are separate from merely adding SECURITY.md or a workflow file. [Repository security settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository), [Private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).

The test workflow grants only `contents: read`, does not persist checkout credentials, uses full Action commit SHAs and avoids privileged `pull_request_target` execution. Dependabot can propose updates; proposals still require review. [Secure use of Actions](https://docs.github.com/en/actions/reference/security/secure-use).

A public repository and an open-source licence are distinct choices. Choose the licence explicitly before publication if reuse is intended. [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

Suggested description: **Desktop tool for manual annotation and measurement of synaptic ribbon profiles in electron micrographs.** Suggested topics: `electron-microscopy`, `annotation`, `neuroscience`, `retina`, `python`, `tkinter`.
