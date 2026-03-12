"""
Auto-push exported CSVs to GitHub for persistent storage.
Uses GitHub API to commit files directly.
"""
import os
import base64
import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime


def push_csv_to_github(csv_path: str, repo: str = None, branch: str = "main", folder: str = "collected_data/climbing"):
    token = os.environ.get("GITHUB_TOKEN")
    repo = repo or os.environ.get("DATA_REPO")

    if not token or not repo:
        print("GitHub sync skipped: GITHUB_TOKEN or DATA_REPO not set")
        return False

    csv_file = Path(csv_path)
    if not csv_file.exists():
        print(f"GitHub sync skipped: file not found {csv_path}")
        return False

    content = csv_file.read_bytes()
    encoded = base64.b64encode(content).decode('utf-8')

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_path = f"{folder}/{timestamp}_{csv_file.name}"

    url = f"https://api.github.com/repos/{repo}/contents/{repo_path}"

    data = json.dumps({
        "message": f"Auto-sync: {csv_file.name} ({timestamp})",
        "content": encoded,
        "branch": branch,
    }).encode('utf-8')

    req = urllib.request.Request(url, data=data, method='PUT')
    req.add_header('Authorization', f'token {token}')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Accept', 'application/vnd.github.v3+json')

    try:
        response = urllib.request.urlopen(req)
        print(f"GitHub sync success: {repo_path}")
        return True
    except urllib.error.HTTPError as e:
        print(f"GitHub sync failed: {e.code} {e.read().decode()}")
        return False
    except Exception as e:
        print(f"GitHub sync error: {e}")
        return False
