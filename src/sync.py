#!/usr/bin/env python3
"""Sync a repo's decisions + verdicts to Precedent Cloud (optional). The enforcement engine stays
local; this just PUSHES the registry so humans/agents can browse and query it in the console.

Config (env or .precedent/.env):
  PRECEDENT_CLOUD_URL    e.g. https://your-app.vercel.app
  PRECEDENT_TEAM_TOKEN   a scoped, revocable team token (minted in the console)
  PRECEDENT_REPO         optional "owner/name" (defaults to the git remote)

Usage:
  python3 src/sync.py            # push decisions.json + captured.json + verdicts.jsonl
  python3 src/sync.py --dry-run  # print the payload, don't send
"""
import json, os, subprocess, sys, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import govern, precedent


def _cfg(k):
    v = os.environ.get(k)
    if v:
        return v
    envf = os.path.join(govern.REPO, ".precedent", ".env")
    if os.path.exists(envf):
        for line in open(envf):
            if line.startswith(k + "="):
                return line.split("=", 1)[1].strip()
    return None


def _repo_name():
    if os.environ.get("PRECEDENT_REPO"):
        return os.environ["PRECEDENT_REPO"]
    try:
        url = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True,
                                      cwd=govern.REPO, stderr=subprocess.DEVNULL).strip()
        return url.split("github.com")[-1].lstrip(":/").removesuffix(".git")
    except Exception:
        return os.path.basename(govern.REPO)


def _read_jsonl(rel):
    p = os.path.join(govern.REPO, ".precedent", rel)
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def build_payload():
    decisions = list(govern.DECISIONS)                    # committed store (repo + org/team merged)
    capf = os.path.join(govern.REPO, ".precedent", "captured.json")
    if os.path.exists(capf):
        decisions += json.load(open(capf)).get("precedents", [])
    return {
        "repo": _repo_name(),
        "decisions": [{"ext_id": d.get("id"), "decision": d.get("decision"),
                       "reasoning": d.get("reasoning", ""), "authority": d.get("authority", "unconfirmed"),
                       "level": d.get("scope", {}).get("level", "repo"),
                       "scope_paths": d.get("scope", {}).get("paths", []),
                       "category": d.get("category"), "provenance": d.get("provenance") or d.get("source"),
                       "enrichment": d.get("enrichment")} for d in decisions],
        "verdicts": _read_jsonl("verdicts.jsonl"),
        "events": _read_jsonl("events.jsonl"),
    }


def main():
    payload = build_payload()
    if "--dry-run" in sys.argv:
        print(json.dumps(payload, indent=2)[:2000] + "\n... ("
              f"{len(payload['decisions'])} decisions, {len(payload['verdicts'])} verdicts, "
              f"{len(payload['events'])} events)")
        return
    url, token = _cfg("PRECEDENT_CLOUD_URL"), _cfg("PRECEDENT_TEAM_TOKEN")
    if not url or not token:
        sys.exit("set PRECEDENT_CLOUD_URL and PRECEDENT_TEAM_TOKEN (see the console) to sync.")
    req = urllib.request.Request(url.rstrip("/") + "/api/ingest",
                                 data=json.dumps(payload).encode(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=30))
    print(f"✓ synced {r.get('decisions', len(payload['decisions']))} decisions, "
          f"{r.get('verdicts', len(payload['verdicts']))} verdicts to {url}")


if __name__ == "__main__":
    main()
