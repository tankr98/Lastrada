#!/usr/bin/env python3
"""Manage the isolated SRI deployment; never update the original stack."""

import argparse
import json
from pathlib import Path
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "lastrada-64bab"
REGION = "us-central1"
BRANCH = "local/stem-fast-v-SRI"
SITE = "lastrada-sri"
PREFIX = "lastrada-sri"
BUCKET = PROJECT + "-lastrada-sri-cases"
QUEUE = PREFIX + "-analysis"
ORIGINS = [f"https://{SITE}.web.app", f"https://{SITE}.firebaseapp.com"]
PERMISSIONS = [
    "run.services.create", "run.services.get", "run.services.update",
    "run.services.getIamPolicy", "run.services.setIamPolicy",
    "iam.serviceAccounts.create", "iam.serviceAccounts.get", "iam.serviceAccounts.actAs",
    "iam.serviceAccounts.getIamPolicy", "iam.serviceAccounts.setIamPolicy",
    "storage.buckets.create", "storage.buckets.get", "storage.buckets.update",
    "storage.buckets.getIamPolicy", "storage.buckets.setIamPolicy",
    "cloudtasks.queues.create", "cloudtasks.queues.get", "cloudtasks.queues.update",
    "cloudtasks.queues.getIamPolicy", "cloudtasks.queues.setIamPolicy",
    "firebasehosting.sites.create", "firebasehosting.sites.get",
    "firebasehosting.sites.update", "firebaseauth.configs.get", "firebaseauth.configs.update",
]


def run(*args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {args[1]} failed: {result.stderr[-2000:]}")
    return result.stdout.strip()


def request(url, *, token=None, method="GET", data=None, allow_missing=False):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(url, method=method, headers=headers,
                  data=None if data is None else json.dumps(data).encode())
    try:
        with urlopen(req, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404 and allow_missing:
            return None
        raise RuntimeError(f"{method} {url} returned HTTP {error.code}") from None


def inspect():
    token = run("gcloud", "auth", "print-access-token")
    permissions = request(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}:testIamPermissions",
        token=token, method="POST", data={"permissions": PERMISSIONS},
    ).get("permissions", [])
    site = request(
        f"https://firebasehosting.googleapis.com/v1beta1/projects/{PROJECT}/sites/{SITE}",
        token=token, allow_missing=True,
    )
    original = request("https://lastrada-alt.web.app/config.json")
    services = {}
    for role in ("api", "worker"):
        service = json.loads(run(
            "gcloud", "run", "services", "describe", f"lastrada-{role}",
            "--project", PROJECT, "--region", REGION, "--format=json",
        ))
        services[role] = {
            "revision": service["status"].get("latestReadyRevisionName"),
            "url": service["status"]["url"],
        }
    result = {
        "project": PROJECT, "branch": BRANCH, "site": SITE,
        "site_exists": site is not None,
        "original_build": original.get("build"), "original_services": services,
        "missing_project_permissions": sorted(set(PERMISSIONS) - set(permissions)),
    }
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["inspect"], default="inspect")
    parser.parse_args()
    inspect()
