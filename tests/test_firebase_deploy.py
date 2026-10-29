import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def bootstrap():
    spec = importlib.util.spec_from_file_location(
        "firebase_bootstrap", ROOT / "deploy/bootstrap.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deployment_defaults_to_plan_and_requires_specific_approval():
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/bootstrap.py")], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "PLAN ONLY" in result.stdout
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/bootstrap.py"), "--apply"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "after approval" in result.stderr


def test_resource_plan_is_bounded_and_uses_existing_project_model():
    module = bootstrap()
    plan = module.plan("lastrada-64bab", "us-central1")
    assert "max 1" in plan["worker"]
    assert "25-minute" in plan["worker"]
    assert "20 globally" in plan["quotas"]
    assert (
        module.DEFAULT_MODEL
        == "https://storage.googleapis.com/lastrada-model-files-sri/sampleid-best.ckpt"
    )


def test_container_starts_api_not_streamlit_and_excludes_private_files():
    docker = (ROOT / "deploy/Dockerfile").read_text()
    assert "uvicorn lastrada.web.server:app" in docker
    assert "streamlit run" not in docker
    ignored = (ROOT / ".dockerignore").read_text()
    assert ignored.startswith("*\n")
    assert "!checkpoints" not in ignored and "!attachments" not in ignored


def test_apply_plan_uses_private_worker_and_never_enables_billing(monkeypatch, tmp_path):
    import json

    module = bootstrap()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "web/public").mkdir(parents=True)
    monkeypatch.setattr(module.shutil, "which", lambda _command: "/tool")
    monkeypatch.setattr(module, "exists", lambda *_args: False)
    calls = []

    def run(*command, capture=False):
        calls.append(command)
        if command[:4] == ("gcloud", "config", "get-value", "account"):
            return "owner@example.test"
        if command[:4] == ("gcloud", "billing", "projects", "describe"):
            return json.dumps({"billingEnabled": True})
        if command[:2] == ("git", "rev-parse"):
            return "testcommit"
        if command[:4] == ("gcloud", "run", "services", "describe"):
            return "https://" + command[4] + ".example.test"
        if "apps:list" in command:
            return json.dumps({"result": [{"platform": "WEB", "appId": "test-app"}]})
        if "apps:sdkconfig" in command:
            return json.dumps(
                {"result": {"sdkConfig": {"projectId": "lastrada-64bab", "apiKey": "public-test"}}}
            )
        if command[:3] == ("gcloud", "builds", "submit"):
            build = json.loads(Path(command[command.index("--config") + 1]).read_text())
            assert build["steps"][0]["env"] == ["DOCKER_BUILDKIT=1"]
        return "" if capture else None

    monkeypatch.setattr(module, "run", run)
    module.apply("lastrada-64bab", "us-central1", module.DEFAULT_MODEL)
    deploys = [c for c in calls if c[:3] == ("gcloud", "run", "deploy")]
    worker = next(c for c in deploys if c[3] == "lastrada-worker")
    api = next(c for c in deploys if c[3] == "lastrada-api")
    assert "--no-allow-unauthenticated" in worker
    assert "--max-instances=1" in worker
    assert "--allow-unauthenticated" in api
    assert not any("link" in c and "billing" in c for c in calls)
    assert not any("keys" in c for c in calls)
    config = json.loads((tmp_path / "web/public/config.json").read_text())
    assert config["firebase"]["projectId"] == "lastrada-64bab"
