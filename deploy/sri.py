#!/usr/bin/env python3
"""Manage the isolated SRI deployment; never update the original stack."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
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
AUTH_CONFIG_URL = f"https://identitytoolkit.googleapis.com/admin/v2/projects/{PROJECT}/config"
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
MARKER = "sri"
FIREBASE = ["npx", "--yes", "firebase-tools@15.4.0"]


def cloud(*args):
    return json.loads(run("gcloud", *args, "--project", PROJECT, "--format=json"))


def account(role):
    return f"{PREFIX}-{role}@{PROJECT}.iam.gserviceaccount.com"


def run(*args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {args[1]} failed: {result.stderr[-2000:]}")
    return result.stdout.strip()


def grant_access(*args, member_role, iam_role):
    """Retry only a rejected binding for a not-yet-propagated SRI account."""
    if member_role not in {"api", "worker", "tasks"}:
        raise ValueError("Only SRI runtime accounts can receive these bindings")
    email = account(member_role)
    delays = (5, 10, 20, 30, 30)
    for attempt in range(len(delays) + 1):
        try:
            return run(*args, "--member", "serviceAccount:" + email, "--role", iam_role)
        except RuntimeError as error:
            message = str(error).lower()
            # Do not retry permission denials, uncertain timeouts, or unrelated
            # missing resources. This 400 rejects the idempotent IAM binding.
            if ("httperror 400" not in message or
                    f"service account {email} does not exist" not in message):
                raise
            if attempt == len(delays):
                raise RuntimeError(
                    f"Google Cloud still does not recognize {email} after "
                    f"{sum(delays)} seconds of waiting. Rerun the SRI deployment "
                    "after account creation propagates; existing SRI resources are retained."
                ) from error
            print(f"Waiting {delays[attempt]}s for Google Cloud to recognize {email}...", flush=True)
            time.sleep(delays[attempt])


def request(url, *, token=None, method="GET", data=None, allow_missing=False):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
        if url == AUTH_CONFIG_URL or url.startswith(AUTH_CONFIG_URL + "?"):
            # Cloud Shell user tokens need an explicit quota project for this
            # client-based API. This does not change the caller's permissions.
            headers["X-Goog-User-Project"] = PROJECT
    req = Request(url, method=method, headers=headers,
                  data=None if data is None else json.dumps(data).encode())
    try:
        with urlopen(req, timeout=60) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404 and allow_missing:
            return None
        detail = google_error_detail(error, token)
        raise RuntimeError(f"{method} {url} returned HTTP {error.code}" +
                           (f": {detail}" if detail else "")) from None


def google_error_detail(error, token):
    """Retain Google's reason for a rejection without logging credentials."""
    try:
        payload = json.loads(error.read(16384))
    except (ValueError, OSError):
        return ""
    problem = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(problem, dict):
        return ""
    parts = [str(problem.get("message", ""))]
    details = problem.get("details", [])
    for item in details if isinstance(details, list) else []:
        if not isinstance(item, dict) or item.get("@type") != "type.googleapis.com/google.rpc.ErrorInfo":
            continue
        parts.append(str(item.get("reason", "")))
        metadata = item.get("metadata", {})
        if isinstance(metadata, dict):
            parts.extend(f"{key}={metadata[key]}" for key in ("service", "consumer", "permission")
                         if key in metadata)
    text = "; ".join(part for part in parts if part)
    return (text.replace(token, "[redacted]") if token else text)[:2000]


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
    print("::notice title=SRI deployment readiness::" + json.dumps(result))
    return result


def source_identity(sha):
    branch = os.getenv("GITHUB_REF_NAME") or run("git", "branch", "--show-current")
    if branch != BRANCH or not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
        raise ValueError(f"Deploy from {BRANCH} with its exact 40-character commit")
    if run("git", "rev-parse", "HEAD") != sha or run("git", "status", "--porcelain"):
        raise ValueError("Deployment requires a clean checkout of the requested commit")
    return {"branch": BRANCH, "commit": sha, "profile": "stem-fast", "dirty": False}


def original_snapshot():
    """Read original services, traffic, access and Hosting configuration unchanged."""
    return {
        "hosting": request("https://lastrada-alt.web.app/config.json"),
        **{
            f"{role}_{operation}": cloud(
                "run", "services", operation, f"lastrada-{role}", "--region", REGION
            )
            for role in ("api", "worker")
            for operation in ("describe", "get-iam-policy")
        },
    }


def ensure_marked(resource):
    if resource and resource.get("labels", {}).get("lastrada-managed") != MARKER:
        raise ValueError("Refusing to modify an existing resource without the SRI marker")


def service_environment(role, identity, original, worker_url=None):
    old_env = {
        item["name"]: item.get("value")
        for item in original[f"{role}_describe"]["spec"]["template"]["spec"]["containers"][0].get("env", [])
    }
    env = {
        key: old_env[key]
        for key in ("LASTRADA_USER_DAILY_JOBS", "LASTRADA_DAILY_JOBS", "LASTRADA_SAMPLEID_CHECKPOINT_URL")
        if old_env.get(key)
    }
    env.update({
        "GOOGLE_CLOUD_PROJECT": PROJECT,
        "LASTRADA_REGION": REGION,
        "LASTRADA_BUILD_SHA": identity["commit"],
        "LASTRADA_BUILD_BRANCH": BRANCH,
        "LASTRADA_CASE_BUCKET": BUCKET,
        "LASTRADA_TASK_QUEUE": QUEUE,
        "LASTRADA_ACCESS": "google",
        "LASTRADA_SERVICE_MODE": role,
        "LASTRADA_ORIGINS": ",".join(ORIGINS),
    })
    if role == "api":
        if not worker_url:
            raise ValueError("SRI worker URL is required")
        env.update(LASTRADA_WORKER_URL=worker_url, LASTRADA_TASK_ACCOUNT=account("tasks"))
    return env


def verify_access(api_url, worker_url):
    checks = [
        (api_url + "/api/analyses/00000000-0000-4000-8000-000000000001", "GET", {}, {401}),
        (worker_url + "/health", "GET", {}, {401, 403}),
        (api_url + "/api/analyses", "OPTIONS", {
            "Origin": ORIGINS[0], "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }, {200}),
    ]
    for url, method, headers, expected in checks:
        try:
            with urlopen(Request(url, method=method, headers=headers), timeout=60) as response:
                status, received = response.status, response.headers
        except HTTPError as error:
            status, received = error.code, error.headers
        if status not in expected:
            raise ValueError(f"SRI access check failed: {method} {url} returned {status}")
        if method == "OPTIONS" and received.get("access-control-allow-origin") != ORIGINS[0]:
            raise ValueError("SRI API did not authorize the new Hosting origin")


def deploy(sha, image):
    identity = source_identity(sha)
    if image != f"ghcr.io/tankr98/lastrada:{sha}":
        raise ValueError("Use the image built and tested for this exact SRI commit")
    original = original_snapshot()
    if original["hosting"].get("firebase", {}).get("projectId") != PROJECT:
        raise ValueError("Original Firebase configuration does not match this project")
    token = run("gcloud", "auth", "print-access-token")

    def api(path, **kwargs):
        return request(path, token=token, **kwargs)

    # Fail before provisioning if the Cloud Shell identity cannot read Auth.
    print("Checking Firebase sign-in configuration access...", flush=True)
    api(AUTH_CONFIG_URL)

    # All newly provisioned resources have SRI names and their own identities.
    print("Preparing the separate SRI service accounts...", flush=True)
    for role in ("api", "worker", "tasks"):
        url = f"https://iam.googleapis.com/v1/projects/{PROJECT}/serviceAccounts/{account(role)}"
        current = api(url, allow_missing=True)
        description = "Managed by Lastrada SRI deployment"
        if current and current.get("description") != description:
            raise ValueError("Refusing to reuse an unmarked service account")
        if current is None:
            run("gcloud", "iam", "service-accounts", "create", f"{PREFIX}-{role}",
                "--project", PROJECT, "--description", description)

    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)

        def json_file(name, value):
            path = temp / name
            path.write_text(json.dumps(value))
            return str(path)

        print("Preparing private SRI uploads and the processing queue...", flush=True)
        bucket = api(f"https://storage.googleapis.com/storage/v1/b/{BUCKET}", allow_missing=True)
        ensure_marked(bucket)
        if bucket is None:
            # Create with ownership marker atomically so interrupted runs can resume.
            api(f"https://storage.googleapis.com/storage/v1/b?project={PROJECT}", method="POST", data={
                "name": BUCKET, "location": REGION, "labels": {"lastrada-managed": MARKER},
                "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True},
                                     "publicAccessPrevention": "enforced"},
            })
        run("gcloud", "storage", "buckets", "update", f"gs://{BUCKET}",
            "--public-access-prevention", "--lifecycle-file", json_file("lifecycle.json", {
                "rule": [{"action": {"type": "Delete"}, "condition": {"age": 7}}],
            }), "--cors-file", json_file("cors.json", [{
                "origin": ORIGINS, "method": ["PUT", "POST", "GET", "HEAD"],
                "responseHeader": ["Content-Type", "Location", "Range", "ETag"], "maxAgeSeconds": 3600,
            }]))
        for role in ("api", "worker"):
            grant_access("gcloud", "storage", "buckets", "add-iam-policy-binding", f"gs://{BUCKET}",
                         member_role=role, iam_role="roles/storage.objectUser")

        parent = f"projects/{PROJECT}/locations/{REGION}"
        queue_url = f"https://cloudtasks.googleapis.com/v2/{parent}/queues/{QUEUE}"
        queue = api(queue_url, allow_missing=True)
        if queue is None:
            api(f"https://cloudtasks.googleapis.com/v2/{parent}/queues", method="POST", data={
                "name": f"{parent}/queues/{QUEUE}",
                "rateLimits": {"maxConcurrentDispatches": 1, "maxDispatchesPerSecond": 1},
                "retryConfig": {"maxAttempts": 3, "minBackoff": "30s", "maxBackoff": "300s"},
            })
        # Queue-scoped permission, without changing the project's IAM policy.
        policy = api(queue_url + ":getIamPolicy", method="POST", data={})
        binding = {"role": "roles/cloudtasks.enqueuer", "members": ["serviceAccount:" + account("api")]}
        bindings = policy.setdefault("bindings", [])
        if binding not in bindings:
            bindings.append(binding)
            api(queue_url + ":setIamPolicy", method="POST", data={"policy": policy})
        grant_access("gcloud", "iam", "service-accounts", "add-iam-policy-binding", account("tasks"),
                     "--project", PROJECT, member_role="api", iam_role="roles/iam.serviceAccountUser")

        worker_url = None
        for role in ("worker", "api"):
            name = f"{PREFIX}-{role}"
            print(f"Deploying {name} (the first container start can take a few minutes)...", flush=True)
            service = api(f"https://run.googleapis.com/v2/{parent}/services/{name}", allow_missing=True)
            ensure_marked(service)
            env = service_environment(role, identity, original, worker_url)
            worker = role == "worker"
            run("gcloud", "run", "deploy", name, "--project", PROJECT, "--region", REGION,
                "--image", image, "--labels=lastrada-managed=sri", "--service-account", account(role),
                "--no-allow-unauthenticated" if worker else "--allow-unauthenticated",
                "--cpu=2" if worker else "--cpu=1", "--memory=4Gi" if worker else "--memory=1Gi",
                "--concurrency=1" if worker else "--concurrency=20", "--min-instances=0",
                "--max-instances=1" if worker else "--max-instances=2",
                "--timeout=1800" if worker else "--timeout=300",
                "--env-vars-file", json_file(role + ".json", env), "--quiet")
            if worker:
                grant_access("gcloud", "run", "services", "add-iam-policy-binding", name,
                             "--project", PROJECT, "--region", REGION,
                             member_role="tasks", iam_role="roles/run.invoker")
            run("gcloud", "run", "services", "update-traffic", name, "--project", PROJECT,
                "--region", REGION, "--to-latest", "--quiet")
            url = cloud("run", "services", "describe", name, "--region", REGION)["status"]["url"]
            if worker:
                worker_url = url
            else:
                api_url = url

        health = request(api_url + "/health")
        if any(health.get(k) != v for k, v in {"status": "ok", "branch": BRANCH, "commit": sha}.items()):
            raise ValueError("SRI API health does not match the requested release")
        verify_access(api_url, worker_url)
        print("Publishing the separate SRI website and enabling its Google sign-in...", flush=True)
        site_url = f"https://firebasehosting.googleapis.com/v1beta1/projects/{PROJECT}/sites"
        if api(site_url + "/" + SITE, allow_missing=True) is None:
            api(site_url + "?siteId=" + SITE, method="POST", data={})

        # Retain every existing Google sign-in domain; only add the SRI hosts.
        # Read again immediately before merging to preserve domains added since
        # the preflight check, including those used by the original website.
        auth = api(AUTH_CONFIG_URL)
        domains = auth.get("authorizedDomains", [])
        additions = [origin.removeprefix("https://") for origin in ORIGINS if origin.removeprefix("https://") not in domains]
        if additions:
            api(AUTH_CONFIG_URL + "?updateMask=authorizedDomains", method="PATCH",
                data={"authorizedDomains": domains + additions})
        config = {**original["hosting"], "apiBase": api_url, "build": identity}
        (ROOT / "web/public/config.json").write_text(json.dumps(config, indent=2) + "\n")
        hosting = json.loads((ROOT / "firebase.json").read_text())
        hosting["hosting"]["site"] = SITE
        hosting["hosting"]["public"] = str(ROOT / "web/public")
        run(*FIREBASE, "deploy", "--only", "hosting", "--project", PROJECT,
            "--config", json_file("firebase.json", hosting), "--non-interactive")
        for attempt in range(6):
            deployed = request(ORIGINS[0] + "/config.json?release=" + sha, allow_missing=True)
            if deployed == config:
                break
            if attempt == 5:
                raise ValueError("SRI Hosting configuration differs from the verified build")
            time.sleep(5)

    if original_snapshot() != original:
        raise ValueError("Original stack changed during deployment; inspect before continuing")
    result = {"site": ORIGINS[0], "api": api_url, "commit": sha, "original_stack_unchanged": True}
    print(json.dumps(result, indent=2))
    print("::notice title=SRI deployed::" + json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["inspect", "apply"], default="inspect")
    parser.add_argument("--sha")
    parser.add_argument("--image")
    args = parser.parse_args()
    if args.mode == "apply":
        deploy(args.sha, args.image)
    else:
        inspect()
