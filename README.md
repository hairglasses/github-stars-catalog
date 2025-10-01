# GitHub Stars Catalog (auto-updating)

This repo auto-builds an organized, categorized list of **@hairglasses**’s starred repositories and publishes it to this README.

- Update cadence: **every 12 hours** (and on manual dispatch).
- Source: GitHub API (GraphQL, with optional REST fallback).
- Categorization: by **primary language** and **top topics**.

> If you want private stars included, create a Personal Access Token (classic) for the same account that owns the stars, give it `repo` scope, and add it to repo secrets as `STAR_FETCH_TOKEN` (see below).

## Output preview

The build writes the sections below on each run. Do not hand-edit between the markers.

<!-- CATALOG:START -->
(pending first run)
<!-- CATALOG:END -->

## Setup

1. **Create the repository** (empty) and push these files.
2. **Secrets** (in repo settings → Secrets and variables → Actions):
   - `STAR_FETCH_TOKEN` *(optional but recommended)*: PAT (classic).  
     - Use `repo` scope to include private-starred repo metadata; `public_repo` is enough if you only need public repos.
   - `STAR_TARGET_USERNAME` *(optional)*: Defaults to the repo owner login detected at runtime; set explicitly to another username if needed (public stars only).
3. **Permissions**: Ensure the workflow’s `GITHUB_TOKEN` has `contents: write` so the Action can commit README updates.
4. **Run the workflow**: It will run every 12 hours and can be triggered manually via the *Actions* tab (`workflow_dispatch`).

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export STAR_FETCH_TOKEN=ghp_your_token   # optional for private stars / rate limits
export STAR_TARGET_USERNAME=hairglasses  # default is repo owner if not set
python scripts/fetch_and_render.py
```

## Notes

- GraphQL is preferred because it returns **topics** and **language** data efficiently. The script handles pagination.
- If GraphQL fails (e.g., missing token when querying non-viewer private data), it falls back to REST for public stars.
- The script writes between `CATALOG:START` and `CATALOG:END` markers only.
