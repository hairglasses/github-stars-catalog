#!/usr/bin/env python3
import os, sys, pathlib, re, requests
from typing import Dict, Any, List, Optional, Tuple
from jinja2 import Template

HERE = pathlib.Path(__file__).resolve().parent.parent
TARGET_PATH = os.getenv("STAR_TARGET_PATH", "README.md")
README = HERE / TARGET_PATH
TPL_TOPIC = HERE / "templates" / "readme_section.topic.j2"
TPL_LANG  = HERE / "templates" / "readme_section.language.j2"

GQL_URL = "https://api.github.com/graphql"
REST_STARS_URL_PUBLIC = "https://api.github.com/users/{username}/starred"

TOPIC_LIMIT_PER_REPO = int(os.getenv("TOPIC_LIMIT_PER_REPO", "50"))  # GraphQL nodes per repo (1..100)
TOPIC_MAX_GROUPS = int(os.getenv("TOPIC_MAX_GROUPS", "200"))
TOPIC_MIN_SIZE = int(os.getenv("TOPIC_MIN_SIZE", "1"))
STAR_GROUP_MODE = os.getenv("STAR_GROUP_MODE", "topic").strip().lower()  # topic | language

def gh_headers(token: Optional[str]) -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def detect_repo_owner() -> str:
    owner = os.getenv("STAR_TARGET_USERNAME")
    if owner:
        return owner
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if "/" in repo:
        return repo.split("/")[0]
    return "hairglasses"

def fetch_stars_graphql(token: Optional[str], username: str) -> List[Dict[str, Any]]:
    q = """
    query($login:String!, $pageSize:Int!, $cursor:String) {
      user(login: $login) {
        starredRepositories(first: $pageSize, after: $cursor, orderBy: {field: STARRED_AT, direction: DESC}) {
          pageInfo { hasNextPage endCursor }
          nodes {
            nameWithOwner
            url
            description
            stargazerCount
            primaryLanguage { name }
            repositoryTopics(first: 100) { nodes { topic { name } } }
          }
        }
      }
    }"""
    headers = gh_headers(token)
    page_size = 100
    cursor = None
    items: List[Dict[str, Any]] = []
    while True:
        payload = {"query": q, "variables": {"login": username, "pageSize": page_size, "cursor": cursor}}
        r = requests.post(GQL_URL, headers=headers, json=payload, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"GraphQL error {r.status_code}: {r.text}")
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        root = data["data"]["user"]
        if not root:
            break
        starred = root["starredRepositories"]
        for node in starred["nodes"]:
            items.append({
                "name_with_owner": node["nameWithOwner"],
                "url": node["url"],
                "description": node.get("description") or "",
                "stars": node.get("stargazerCount", 0),
                "primary_language": (node.get("primaryLanguage") or {}).get("name") or "Other",
                "topics": sorted({n["topic"]["name"] for n in (node.get("repositoryTopics") or {}).get("nodes", [])})[:TOPIC_LIMIT_PER_REPO]
            })
        if not starred["pageInfo"]["hasNextPage"]:
            break
        cursor = starred["pageInfo"]["endCursor"]
    return items

def fetch_stars_rest(token: Optional[str], username: str) -> List[Dict[str, Any]]:
    headers = gh_headers(token)
    url = REST_STARS_URL_PUBLIC.format(username=username)
    page = 1
    per_page = 100
    items: List[Dict[str, Any]] = []
    while True:
        r = requests.get(url, headers=headers, params={"per_page": per_page, "page": page}, timeout=60)
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
                "primary_language": node.get("language") or "Other",
                "topics": sorted(node.get("topics", []))[:TOPIC_LIMIT_PER_REPO],
            })
        if len(batch) < per_page:
            break
        page += 1
    return items

def index_topic_first(repos: List[Dict[str, Any]]):
    by_topic = {}
    uncategorized = []
    for r in repos:
        ts = r.get("topics") or []
        if not ts:
            uncategorized.append(r)
            continue
        for t in ts[:TOPIC_LIMIT_PER_REPO]:
            by_topic.setdefault(t, []).append(r)
    for v in by_topic.values():
        v.sort(key=lambda x: (-(x.get("stars") or 0), x["name_with_owner"].lower()))
    by_topic = {k: v for k, v in by_topic.items() if len(v) >= TOPIC_MIN_SIZE}
    by_topic = dict(sorted(by_topic.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))[:TOPIC_MAX_GROUPS])
    uncategorized.sort(key=lambda x: x["name_with_owner"].lower())
    return by_topic, uncategorized

def index_language_first(repos: List[Dict[str, Any]]):
    by_language = {}
    languages = set()
    for r in repos:
        lang = r.get("primary_language") or "Other"
        languages.add(lang)
        by_language.setdefault(lang, []).append(r)
    for v in by_language.values():
        v.sort(key=lambda x: (-(x.get("stars") or 0), x["name_with_owner"].lower()))
    return by_language, sorted(languages)

def upsert_marked_section(full_text: str, new_section: str) -> tuple[str, bool]:
    """
    Replace catalog section if markers exist (tolerant to whitespace/case).
    If markers are missing, append a fresh block at the end.
    Returns (updated_text, inserted_markers).
    """
    start_re = r"<!--\s*CATALOG:START\s*-->"
    end_re   = r"<!--\s*CATALOG:END\s*-->"
    pat = re.compile(rf"({start_re})(.*?)(?:\r?\n)({end_re})", re.DOTALL | re.IGNORECASE)
    m = pat.search(full_text)
    if m:
        replaced = pat.sub(lambda mm: f"{mm.group(1)}\n{new_section}\n{mm.group(3)}", full_text)
        return replaced, False
    base = full_text.rstrip() + ("\n\n" if full_text.strip() else "")
    block = f"<!-- CATALOG:START -->\n{new_section}\n<!-- CATALOG:END -->\n"
    return base + block, True

def render(repos: List[Dict[str, Any]]) -> str:
    if os.getenv("STAR_GROUP_MODE", "topic").strip().lower() == "language":
        tpl = Template(TPL_LANG.read_text(encoding="utf-8"))
        by_language, languages = index_language_first(repos)
        return tpl.render(repos=repos, by_language=by_language, languages=languages).strip()
    tpl = Template(TPL_TOPIC.read_text(encoding="utf-8"))
    by_topic, uncategorized = index_topic_first(repos)
    return tpl.render(repos=repos, by_topic=by_topic, uncategorized=uncategorized).strip()

def main():
    username = os.getenv("STAR_TARGET_USERNAME", "").strip() or detect_repo_owner()
    token = os.getenv("STAR_FETCH_TOKEN", "").strip() or None
    try:
        repos = fetch_stars_graphql(token, username)
    except Exception as e:
        print("GraphQL failed, falling back to REST:", e, file=sys.stderr)
        repos = []
    if not repos:
        repos = fetch_stars_rest(token, username)
    section = render(repos)
    try:
        readme_text = README.read_text(encoding="utf-8")
    except FileNotFoundError:
        # If a custom target path doesn't exist, create its parent directory
        README.parent.mkdir(parents=True, exist_ok=True)
        readme_text = ""
    updated, inserted = upsert_marked_section(readme_text, section)
    if updated != readme_text:
        README.write_text(updated, encoding="utf-8")
        print(f"{TARGET_PATH} updated." + (" (inserted missing markers)" if inserted else ""))
    else:
        print("No changes.")

if __name__ == "__main__":
    main()
