# GitHub Stars Catalog (topic-first)

This repo auto-builds an organized, categorized list of **@hairglasses**’s starred repositories and publishes it to this README.

- Update cadence: **every 12 hours** (and on manual dispatch).
- Source: GitHub API (GraphQL preferred; REST fallback).
- **Grouping mode:** `STAR_GROUP_MODE` = `topic` (default) or `language`.

> Include private stars by adding a PAT to secrets as `STAR_FETCH_TOKEN` (same account as the stars).

## Output
The build rewrites only the block below on each run. If markers are missing, the workflow will insert them automatically:

<!-- CATALOG:START -->
(pending first run)
<!-- CATALOG:END -->

## Setup

1. Push these files to a new repo.
2. Repo **Settings → Secrets and variables → Actions**:
   - `STAR_FETCH_TOKEN` *(optional)*: PAT (classic). Use `repo` for private stars, `public_repo` for public-only.
   - `STAR_TARGET_USERNAME` *(optional)*: target user; defaults to repo owner.
3. **Optional env**:
   - `STAR_GROUP_MODE=topic|language` — grouping mode
   - `STAR_TARGET_PATH` — file to write to (default `README.md`), e.g. `docs/README.md`
4. The Action runs every 12 hours and on manual dispatch.
