# JSAT Release Guide

## Version Convention (PEP 440)

| Change type | Version format | Example | When to use |
|---|---|---|---|
| Feature or bug fix | bump patch | `0.2.7 → 0.2.8` | New behaviour, any code change users will notice |
| Chore / docs / gitignore | post-release | `0.2.7 → 0.2.7.post1` | No functional change; housekeeping only |
| Pre-release / experiment | alpha or beta | `0.2.8a1`, `0.2.8b1` | Unstable preview before a minor release |

**Rule of thumb:** if `pip install --upgrade jsat` would change runtime behaviour → bump patch.  
If the only change is to `.gitignore`, `CHANGELOG.md`, or a README typo → use `.post1`.

## Release Steps

```bash
# 1. Set the version in both places
sed -i '' 's/version = "OLD"/version = "NEW"/' pyproject.toml
sed -i '' 's/__version__ = "OLD"/__version__ = "NEW"/' jsat/__init__.py

# 2. Commit
git add pyproject.toml jsat/__init__.py
git commit -m "chore: bump to vNEW"

# 3. Push commits first
git push origin main

# 4. Tag — must match pyproject.toml exactly (CI validates this)
git tag vNEW
git push origin vNEW
```

The GitHub Actions publish workflow validates that the tag name matches `pyproject.toml` before building. A mismatch causes the workflow to fail immediately with a clear error message.

## Post-release fix example

```bash
# Only changed README.md after releasing 0.2.8 — no code change needed
sed -i '' 's/version = "0.2.8"/version = "0.2.8.post1"/' pyproject.toml
sed -i '' 's/__version__ = "0.2.8"/__version__ = "0.2.8.post1"/' jsat/__init__.py
git add pyproject.toml jsat/__init__.py
git commit -m "chore: bump to v0.2.8.post1"
git push origin main && git tag v0.2.8.post1 && git push origin v0.2.8.post1
```
