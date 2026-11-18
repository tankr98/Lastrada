"""The experimental deployment must never write to the original stack."""

import importlib.util
from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sri", ROOT / "deploy/sri.py")
sri = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sri)
SHA = "a" * 40


def test_wrong_branch_dirty_tree_or_wrong_sha_stop_before_cloud(monkeypatch):
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    for branch, commit, dirty in [
        ("local/stem-fast", SHA, ""),
        (sri.BRANCH, "b" * 40, ""),
        (sri.BRANCH, SHA, " M app.py"),
    ]:
        calls = []

        def run(*args):
            calls.append(args)
            assert args[0] == "git"
            return {"branch": branch, "rev-parse": commit, "status": dirty}[args[1]]

        monkeypatch.setattr(sri, "run", run)
        with pytest.raises(ValueError):
            sri.deploy(SHA, f"ghcr.io/tankr98/lastrada:{SHA}")
        assert calls


@pytest.mark.parametrize("status,missing", [(404, True), (403, False), (500, False)])
def test_only_not_found_is_treated_as_absent(monkeypatch, status, missing):
    def denied(*args, **kwargs):
        raise HTTPError("https://example.test", status, "error", {}, None)

    monkeypatch.setattr(sri, "urlopen", denied)
    if missing:
        assert sri.request("https://example.test", allow_missing=True) is None
    else:
        with pytest.raises(RuntimeError, match=f"HTTP {status}"):
            sri.request("https://example.test", allow_missing=True)


def test_unmarked_existing_resources_are_not_reused():
    with pytest.raises(ValueError, match="without the SRI marker"):
        sri.ensure_marked({"name": "occupied", "labels": {}})


@pytest.mark.parametrize("api_status,worker_status,origin,valid", [
    (401, 403, sri.ORIGINS[0], True),
    (200, 403, sri.ORIGINS[0], False),
    (401, 200, sri.ORIGINS[0], False),
    (401, 403, "https://lastrada-alt.web.app", False),
])
def test_access_verification_requires_sign_in_private_worker_and_sri_cors(
    monkeypatch, api_status, worker_status, origin, valid,
):
    def respond(req, **kwargs):
        if req.method == "OPTIONS":
            return nullcontext(SimpleNamespace(status=200, headers={"access-control-allow-origin": origin}))
        status = worker_status if req.full_url.startswith("https://worker.test") else api_status
        if status >= 400:
            raise HTTPError(req.full_url, status, "authentication required", {}, None)
        return nullcontext(SimpleNamespace(status=status, headers={}))

    monkeypatch.setattr(sri, "urlopen", respond)
    if valid:
        sri.verify_access("https://api.test", "https://worker.test")
    else:
        with pytest.raises(ValueError):
            sri.verify_access("https://api.test", "https://worker.test")


@pytest.mark.parametrize("resume_with_propagation_delay", [False, True])
def test_new_stack_only_mutates_sri_resources_and_preserves_sign_in(
    monkeypatch, tmp_path, resume_with_propagation_delay,
):
    identity = {"branch": sri.BRANCH, "commit": SHA, "profile": "stem-fast", "dirty": False}
    original = {
        "hosting": {"firebase": {"projectId": sri.PROJECT, "apiKey": "public-key"},
                    "apiBase": "https://original-api.test", "build": {"commit": "old"}},
    }
    for role in ("api", "worker"):
        original[role + "_describe"] = {
            "spec": {"template": {"spec": {"containers": [{"env": [
                {"name": "LASTRADA_CASE_BUCKET", "value": "original-bucket"},
                {"name": "LASTRADA_WORKER_URL", "value": "https://original-worker.test"},
                {"name": "LASTRADA_TASK_ACCOUNT", "value": "original-account"},
                {"name": "LASTRADA_USER_DAILY_JOBS", "value": "25"},
                {"name": "LASTRADA_SAMPLEID_CHECKPOINT_URL", "value": "https://model.test/model.ckpt"},
            ]}]}}},
        }
    monkeypatch.setattr(sri, "ROOT", tmp_path)
    (tmp_path / "web/public").mkdir(parents=True)
    (tmp_path / "firebase.json").write_text(json.dumps({"hosting": {"site": "lastrada-alt"}}))
    monkeypatch.setattr(sri, "source_identity", lambda _: identity)
    monkeypatch.setattr(sri, "verify_access", lambda api, worker: None)
    snapshots = []
    monkeypatch.setattr(sri, "original_snapshot", lambda: snapshots.append(True) or original)
    commands, mutations, envs, waits = [], [], {}, []
    monkeypatch.setattr(sri.time, "sleep", waits.append)

    def run(*args):
        commands.append(args)
        if args[:3] == ("gcloud", "auth", "print-access-token"):
            return "not-a-real-token"
        if (resume_with_propagation_delay and
                args[:4] == ("gcloud", "storage", "buckets", "add-iam-policy-binding") and
                "serviceAccount:" + sri.account("worker") in args and commands.count(args) <= 2):
            raise RuntimeError(
                "gcloud storage failed: ERROR: (gcloud.storage.buckets.add-iam-policy-binding) "
                f"HTTPError 400: Service account {sri.account('worker')} does not exist."
            )
        if args[:3] == ("gcloud", "run", "deploy"):
            assert waits == ([5, 10] if resume_with_propagation_delay else [])
            assert args[3] in {"lastrada-sri-api", "lastrada-sri-worker"}
            envs[args[3]] = json.loads(Path(args[args.index("--env-vars-file") + 1]).read_text())
        if "hosting" in args:
            hosting = json.loads(Path(args[args.index("--config") + 1]).read_text())
            assert hosting["hosting"]["site"] == "lastrada-sri"
        return ""

    def request(url, *, token=None, method="GET", data=None, allow_missing=False):
        if method != "GET":
            mutations.append((url, method, data))
            return {}
        if url.startswith("https://lastrada-sri.web.app/config.json"):
            return json.loads((tmp_path / "web/public/config.json").read_text())
        if allow_missing:
            if resume_with_propagation_delay:
                if "iam.googleapis.com" in url:
                    return {"description": "Managed by Lastrada SRI deployment"}
                if "storage.googleapis.com" in url:
                    return {"labels": {"lastrada-managed": "sri"}}
            return None
        if url.endswith("/health"):
            return {"status": "ok", "branch": sri.BRANCH, "commit": SHA}
        if "identitytoolkit" in url:
            return {"authorizedDomains": ["lastrada-alt.web.app", "custom.example"]}
        raise AssertionError(url)

    monkeypatch.setattr(sri, "run", run)
    monkeypatch.setattr(sri, "request", request)
    monkeypatch.setattr(sri, "cloud", lambda *args: {"status": {"url": f"https://{args[3]}.test"}})
    sri.deploy(SHA, f"ghcr.io/tankr98/lastrada:{SHA}")
    assert len(snapshots) == 2
    for command in commands:
        assert not {"lastrada-api", "lastrada-worker", "lastrada-analysis", "gs://lastrada-64bab-lastrada-cases"}.intersection(command)
        assert command[:3] != ("gcloud", "projects", "add-iam-policy-binding")
    assert all("lastrada-alt" not in url for url, _, _ in mutations)
    auth_changes = [data for url, method, data in mutations if "identitytoolkit" in url]
    assert auth_changes == [{"authorizedDomains": [
        "lastrada-alt.web.app", "custom.example", "lastrada-sri.web.app", "lastrada-sri.firebaseapp.com",
    ]}]
    for env in envs.values():
        assert env["LASTRADA_CASE_BUCKET"] == "lastrada-64bab-lastrada-sri-cases"
        assert env["LASTRADA_TASK_QUEUE"] == "lastrada-sri-analysis"
        assert env["LASTRADA_BUILD_BRANCH"] == sri.BRANCH
        assert env["LASTRADA_USER_DAILY_JOBS"] == "25"
        assert env["LASTRADA_ACCESS"] == "google"
    assert envs["lastrada-sri-api"]["LASTRADA_WORKER_URL"] == "https://lastrada-sri-worker.test"
    assert envs["lastrada-sri-api"]["LASTRADA_TASK_ACCOUNT"] == sri.account("tasks")
    worker = next(c for c in commands if c[:4] == ("gcloud", "run", "deploy", "lastrada-sri-worker"))
    assert "--no-allow-unauthenticated" in worker and "--max-instances=1" in worker
    if resume_with_propagation_delay:
        assert not any(c[:4] == ("gcloud", "iam", "service-accounts", "create") for c in commands)
        assert not any(url == f"https://storage.googleapis.com/storage/v1/b?project={sri.PROJECT}"
                       for url, _, _ in mutations)


@pytest.mark.parametrize("message", [
    "HTTPError 403: Permission denied",
    "HTTPError 400: Invalid role",
    "HTTPError 400: Service account unrelated@example.com does not exist.",
    "HTTPError 403: Service account lastrada-sri-worker@lastrada-64bab.iam.gserviceaccount.com does not exist.",
    "Request timed out; outcome unknown",
])
def test_iam_errors_other_than_sri_account_propagation_are_not_retried(monkeypatch, message):
    calls, waits = [], []

    def fail(*args):
        calls.append(args)
        raise RuntimeError(message)

    monkeypatch.setattr(sri, "run", fail)
    monkeypatch.setattr(sri.time, "sleep", waits.append)
    with pytest.raises(RuntimeError, match=message):
        sri.grant_access("gcloud", "storage", "buckets", "add-iam-policy-binding",
                         f"gs://{sri.BUCKET}", member_role="worker", iam_role="roles/storage.objectUser")
    assert len(calls) == 1 and not waits


def test_account_propagation_wait_is_bounded_and_retains_the_cloud_error(monkeypatch):
    calls, waits = [], []

    def fail(*args):
        calls.append(args)
        raise RuntimeError(f"HTTPError 400: Service account {sri.account('worker')} does not exist.")

    monkeypatch.setattr(sri, "run", fail)
    monkeypatch.setattr(sri.time, "sleep", waits.append)
    with pytest.raises(RuntimeError, match="95 seconds.*existing SRI resources are retained") as caught:
        sri.grant_access("gcloud", "storage", "buckets", "add-iam-policy-binding",
                         f"gs://{sri.BUCKET}", member_role="worker", iam_role="roles/storage.objectUser")
    assert "HTTPError 400" in str(caught.value.__cause__)
    assert len(calls) == 6 and len(set(calls)) == 1
    assert sum(waits) == 95
