#!/usr/bin/env python3
import os, sys, time, json, textwrap, pathlib, re
from typing import Dict, Any, List, Optional, Tuple
import requests
from jinja2 import Template

HERE = pathlib.Path(__file__).resolve().parent.parent
README = HERE / "README.md"
TEMPLATE = HERE / "templates" / "readme_section.j2"

GQL_URL = "https://api.github.com/graphql"
REST_STARS_URL_PUBLIC = "https://api.github.com/users/{username}/starred"
REST_STARS_URL_AUTHED = "https://api.github.com/user/starred"

def gh_headers(token: Optional[str]) -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def detect_repo_owner() -> str:
    # In GitHub Actions, we can read env vars. Fallback to STAR_TARGET_USERNAME or default.
    owner = os.getenv("STAR_TARGET_USERNAME")
    if owner:
        return owner
    # Try GITHUB_REPOSITORY env like "owner/repo"
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" in repo:
        return repo.split("/")[0]
    # Default to provided example
    return "hairglasses"

def fetch_stars_graphql(token: Optional[str], username: str) -> List[Dict[str, Any]]:
    """Try GraphQL for starred repos.
    If token belongs to the same user, use `viewer { starredRepositories }` for private+public.
    Else use `user(login: "...") { starredRepositories }` (public only)."""
    if not token and username != "":
        # Public-only path ok; GraphQL without auth has lower rate limit though (~60/hr).
        pass

    is_viewer = False
    # best-effort check: if STAR_TARGET_USERNAME not set, and token exists, assume viewer
    if token and (username == "" or username is None or username == detect_repo_owner()):
        # If token belongs to the same user that owns the stars, viewer path yields private too.
        is_viewer = True

    q_viewer = """
    query($pageSize:Int!, $cursor:String) {
      viewer {
        starredRepositories(first: $pageSize, after: $cursor, orderBy: {field: STARRED_AT, direction: DESC}) {
          pageInfo { hasNextPage endCursor }
          nodes {
            nameWithOwner
            url
            description
            stargazerCount
            isArchived
            isFork
            primaryLanguage { name }
            repositoryTopics(first: 12) { nodes { topic { name } } }
          }
        }
      }
      rateLimit { remaining resetAt }
    }"""

    q_user = """
    query($login:String!, $pageSize:Int!, $cursor:String) {
      user(login: $login) {
        starredRepositories(first: $pageSize, after: $cursor, orderBy: {field: STARRED_AT, direction: DESC}) {
          pageInfo { hasNextPage endCursor }
          nodes {
            nameWithOwner
            url
            description
            stargazerCount
            isArchived
            isFork
            primaryLanguage { name }
            repositoryTopics(first: 12) { nodes { topic { name } } }
          }
        }
      }
      rateLimit { remaining resetAt }
    }"""

    headers = gh_headers(token)
    page_size = 100
    cursor = None
    items: List[Dict[str, Any]] = []

    while True:
        if is_viewer:
            variables = {"pageSize": page_size, "cursor": cursor}
            payload = {"query": q_viewer, "variables": variables}
        else:
            variables = {"login": username, "pageSize": page_size, "cursor": cursor}
            payload = {"query": q_user, "variables": variables}
        r = requests.post(GQL_URL, headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"GraphQL error {r.status_code}: {r.text}")
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        root = data["data"]["viewer" if is_viewer else "user"]
        if not root:
            # Likely querying a username with no stars or missing auth; bail to REST
            break
        starred = root["starredRepositories"]
        for node in starred["nodes"]:
            items.append({
                "name_with_owner": node["nameWithOwner"],
                "url": node["url"],
                "description": node.get("description") or "",
                "stars": node.get("stargazerCount", 0),
                "primary_language": (node.get("primaryLanguage") or {}).get("name"),
                "topics": [n["topic"]["name"] for n in (node.get("repositoryTopics") or {}).get("nodes", [])]
            })
        if not starred["pageInfo"]["hasNextPage"]:
            break
        cursor = starred["pageInfo"]["endCursor"]
    return items

def fetch_stars_rest(token: Optional[str], username: str) -> List[Dict[str, Any]]:
    headers = gh_headers(token)
    url = REST_STARS_URL_AUTHED if token and username == detect_repo_owner() else REST_STARS_URL_PUBLIC.format(username=username)
    page = 1
    per_page = 100
    items: List[Dict[str, Any]] = []
    while True:
        r = requests.get(url, headers=headers, params={"per_page": per_page, "page": page}, timeout=60)
        if r.status_code == 404 and "user/starred" in url:
            # Token isn't the starrer; fall back to public endpoint
            url = REST_STARS_URL_PUBLIC.format(username=username)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"REST error {r.status_code}: {r.text}")
        batch = r.json()
        if not batch:
            break
        for node in batch:
            items.append({
                "name_with_owner": node["full_name"],
                "url": node["html_url"],
                "description": node.get("description") or "",
                "stars": node.get("stargazers_count", 0),
                "primary_language": node.get("language"),
                "topics": node.get("topics", []),
            })
        if len(batch) < per_page:
            break
        page += 1
    return items

def normalize(repos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for r in repos:
        if r.get("primary_language") is None:
            r["primary_language"] = "Other"
        r["topics"] = sorted(set([t.strip() for t in (r.get("topics") or []) if t]))
    return repos

def build_indexes(repos: List[Dict[str, Any]]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]], List[str]]:
    by_lang: Dict[str, List[Dict[str, Any]]] = {}
    by_topic: Dict[str, List[Dict[str, Any]]] = {}
    languages = set()
    for r in repos:
        lang = r["primary_language"] or "Other"
        languages.add(lang)
        by_lang.setdefault(lang, []).append(r)
        for t in r["topics"][:5]:
            by_topic.setdefault(t, []).append(r)
    # sort each
    for v in by_lang.values():
        v.sort(key=lambda x: (-(x.get("stars") or 0), x["name_with_owner"].lower()))
    for v in by_topic.values():
        v.sort(key=lambda x: (-(x.get("stars") or 0), x["name_with_owner"].lower()))
    return by_lang, by_topic, sorted(languages)

def render_section(repos: List[Dict[str, Any]]) -> str:
    tmpl = Template(TEMPLATE.read_text(encoding="utf-8"))
    by_lang, by_topic, languages = build_indexes(repos)
    top_topic_count = 30  # cap display
    # keep only top N topics by item count
    by_topic = dict(sorted(by_topic.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))[:top_topic_count])
    return tmpl.render(
        repos=repos,
        by_language=by_lang,
        by_topic=by_topic,
        languages=languages,
        top_topic_count=top_topic_count,
    ).strip()

def replace_between_markers(full_text: str, new_section: str, start="<!-- CATALOG:START -->", end="<!-- CATALOG:END -->") -> str:
    pattern = re.compile(rf"({re.escape(start)})(.*?)[\r\n]+({re.escape(end)})", re.DOTALL)
    if not pattern.search(full_text):
        raise RuntimeError("Markers not found in README.md")
    return pattern.sub(lambda m: f"{m.group(1)}\n{new_section}\n{m.group(3)}", full_text)

def main():
    username = os.getenv("STAR_TARGET_USERNAME", "").strip()
    if not username:
        username = detect_repo_owner()
    token = os.getenv("STAR_FETCH_TOKEN", "").strip() or None

    repos = []
    try:
        repos = fetch_stars_graphql(token, username)
    except Exception as e:
        print("GraphQL path failed, will try REST:", e, file=sys.stderr)
    if not repos:
        repos = fetch_stars_rest(token, username)

    repos = normalize(repos)

    section = render_section(repos)
    readme_text = README.read_text(encoding="utf-8")
    updated = replace_between_markers(readme_text, section)

    if updated != readme_text:
        README.write_text(updated, encoding="utf-8")
        print("README.md updated.")
    else:
        print("No changes.")

if __name__ == "__main__":
    main()
