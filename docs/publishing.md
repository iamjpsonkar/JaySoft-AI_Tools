# Publishing

This page covers publishing the JSAT package to PyPI and deploying the documentation site to GitHub Pages.

---

## Publishing to PyPI

### Prerequisites

```bash
pip install build twine
```

You need a PyPI account and an API token. Generate one at [pypi.org/manage/account/token/](https://pypi.org/manage/account/token/).

### Build the distribution

```bash
cd /path/to/JaySoft-AI_Tools
python -m build
```

This creates `dist/jsat-<version>.tar.gz` and `dist/jsat-<version>-py3-none-any.whl`.

### Upload to PyPI

```bash
twine upload dist/*
```

Enter your PyPI username and the API token as the password (or configure `~/.pypirc`).

### Using `~/.pypirc`

```ini
[distutils]
index-servers = pypi

[pypi]
username = __token__
password = pypi-...your-token...
```

Then just run `twine upload dist/*` without interactive prompts.

### Test on TestPyPI first

```bash
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ jsat
```

---

## Bumping the Version

The version is set in two places:

1. `pyproject.toml` — `version = "0.1.0"`
2. `jsat/__init__.py` — `__version__ = "0.1.0"`

Update both before building. There is no automated sync; keep them in sync manually or add a pre-build check.

---

## Deploying Documentation

JSAT docs use [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) and are deployed to GitHub Pages.

### Install MkDocs

```bash
pip install mkdocs mkdocs-material
```

### Preview locally

```bash
mkdocs serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. The server reloads automatically when you edit any `.md` file.

### Build the static site

```bash
mkdocs build
```

Creates a `site/` directory with static HTML.

### Deploy to GitHub Pages

```bash
mkdocs gh-deploy
```

This builds the site and force-pushes it to the `gh-pages` branch of your repository. GitHub Pages serves from that branch automatically.

The site will be available at:

```
https://iamjpsonkar.github.io/JaySoft-AI-Tools
```

### Automated deployment with GitHub Actions

Create `.github/workflows/docs.yml`:

```yaml
name: Deploy docs

on:
  push:
    branches:
      - main
    paths:
      - 'docs/**'
      - 'mkdocs.yml'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # required for mkdocs gh-deploy

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install docs dependencies
        run: pip install mkdocs mkdocs-material

      - name: Deploy
        run: mkdocs gh-deploy --force
```

With this workflow, documentation is published automatically on every push to `main` that touches `docs/` or `mkdocs.yml`.

---

## Automated PyPI Publish with GitHub Actions

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  build-and-publish:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write  # required for trusted publishing

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install build tools
        run: pip install build

      - name: Build
        run: python -m build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

This uses PyPI Trusted Publishing (OIDC) — no API token stored in GitHub secrets. Configure Trusted Publishing in your PyPI project settings under "Publishing".

To publish a new version:

1. Bump `version` in `pyproject.toml` and `jsat/__init__.py`
2. Commit and push
3. Create a GitHub Release — the workflow publishes to PyPI automatically

---

## Release Checklist

- [ ] Update `version` in `pyproject.toml`
- [ ] Update `__version__` in `jsat/__init__.py`
- [ ] Update `CHANGELOG.md`
- [ ] Run tests: `pytest tests/`
- [ ] Build: `python -m build`
- [ ] Test install from wheel: `pip install dist/jsat-<version>-py3-none-any.whl`
- [ ] Upload to TestPyPI and verify
- [ ] Upload to PyPI: `twine upload dist/*`
- [ ] Create GitHub Release (triggers automated publish if using the workflow)
- [ ] Deploy docs: `mkdocs gh-deploy`
