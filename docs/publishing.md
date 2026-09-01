# Publishing

This page covers publishing the JSAT package to PyPI and deploying the documentation site to GitHub Pages.

---

## Publishing to PyPI

**The primary release path is automated and does not require a manual upload.** JSAT
publishes to PyPI using [trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC) via `.github/workflows/publish.yml`: pushing a version tag builds the package in CI
and PyPI authenticates the workflow directly — no token is uploaded or stored for the normal
release path. `secrets.PYPI_API_TOKEN` exists only as an optional fallback input to that
workflow, not as something you use by hand.

Follow **[RELEASING.md](https://github.com/iamjpsonkar/JaySoft-AI-Tools/blob/main/RELEASING.md)**
in the repo root for the exact, current release steps: bump the version in `pyproject.toml`
and `jsat/__init__.py`, commit, push to `main`, then `git tag vX.Y.Z && git push origin
vX.Y.Z`. That tag push triggers `publish.yml`, which builds the distribution and publishes it
to PyPI via trusted publishing. See [Bumping the Version](#bumping-the-version) below for
detail on the two files that must stay in sync.

### Manual/fallback publish (only if you need to bypass the automated workflow)

Use this path only when you specifically need to publish without going through
`publish.yml` — for example, testing a build locally or recovering from a workflow outage.
It is not the normal release process.

```bash
pip install build twine
```

You need a PyPI account and an API token. Generate one at [pypi.org/manage/account/token/](https://pypi.org/manage/account/token/).

```bash
cd /path/to/JaySoft-AI_Tools
python -m build
```

This creates `dist/jsat-<version>.tar.gz` and `dist/jsat-<version>-py3-none-any.whl`.

```bash
twine upload dist/*
```

Enter your PyPI username and the API token as the password (or configure `~/.pypirc`):

```ini
[distutils]
index-servers = pypi

[pypi]
username = __token__
password = pypi-...your-token...
```

With `~/.pypirc` configured, `twine upload dist/*` runs without interactive prompts.

Test on TestPyPI first if you're unsure about a manual upload:

```bash
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ jsat
```

---

## Bumping the Version

The version is set in two places:

1. `pyproject.toml` — `version = "<new-version>"`
2. `jsat/__init__.py` — `__version__ = "<new-version>"`

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

This is the real, current release path — see `.github/workflows/publish.yml` in the repo:

```yaml
name: Publish to PyPI

on:
  push:
    tags:
      - "v*"          # triggers on: git tag v0.1.0 && git push --tags

jobs:
  publish:
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/project/jsat/

    permissions:
      id-token: write   # required for trusted publishing (no token needed!)

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install build tools
        run: pip install build tomli

      - name: Validate version tag matches pyproject.toml
        run: |
          # Fails the workflow if the pushed tag (vX.Y.Z) doesn't match
          # the version in pyproject.toml — see RELEASING.md.

      - name: Build
        run: python -m build

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}
          skip-existing: true
```

The workflow triggers on **pushing a version tag** (`vX.Y.Z`), not on creating a GitHub
Release. It authenticates to PyPI via **trusted publishing (OIDC)** using the `id-token:
write` permission — `secrets.PYPI_API_TOKEN` is passed through as an optional fallback input
to `pypa/gh-action-pypi-publish` and is not required for trusted publishing to work. Trusted
publishing must be configured once in the PyPI project's settings under "Publishing," linking
it to this repo and workflow file. Before building, the workflow validates that the pushed
tag matches the `version` in `pyproject.toml` and fails fast with a clear error on a mismatch.

To publish a new version, follow **[RELEASING.md](https://github.com/iamjpsonkar/JaySoft-AI-Tools/blob/main/RELEASING.md)**:

1. Bump `version` in `pyproject.toml` and `__version__` in `jsat/__init__.py`
2. Commit and push to `main`
3. `git tag vX.Y.Z && git push origin vX.Y.Z` — this triggers the workflow above

---

## Release Checklist

- [ ] Update `version` in `pyproject.toml`
- [ ] Update `__version__` in `jsat/__init__.py`
- [ ] Update `CHANGELOG.md`
- [ ] Run tests: `pytest tests/`
- [ ] Commit and push to `main`
- [ ] Tag the release: `git tag vX.Y.Z && git push origin vX.Y.Z` (see [RELEASING.md](https://github.com/iamjpsonkar/JaySoft-AI-Tools/blob/main/RELEASING.md)) — triggers the automated PyPI publish via trusted publishing
- [ ] Confirm the `publish.yml` run succeeded and the new version is live on PyPI
- [ ] Deploy docs: `mkdocs gh-deploy` (if not already covered by the docs workflow)

Only fall back to the manual `python -m build` + `twine upload` path above if you must
publish without going through the automated workflow.
