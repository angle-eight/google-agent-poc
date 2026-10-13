from helpdesk.config import Settings
from helpdesk.platform_client import AgentEngineConfig
from scripts.deploy_agent import deployment_config, deployment_files


def test_deployment_matches_installed_sdk_and_avoids_reserved_env_vars():
    config = deployment_config(Settings(project="test", staging_bucket="gs://test"), "test")
    validated = AgentEngineConfig(**config)
    assert validated.agent_framework == "google-adk"
    assert validated.staging_bucket == "gs://test"
    assert validated.min_instances == 0
    assert "GOOGLE_CLOUD_PROJECT" not in config["env_vars"]
    assert "GOOGLE_CLOUD_LOCATION" not in config["env_vars"]
    assert "SESSION_SECRET" not in config["env_vars"]
    assert all("==" in requirement for requirement in config["requirements"])
    assert "helpdesk/agent.py" in config["extra_packages"]
    assert "helpdesk/data/knowledge.json" in config["extra_packages"]


def test_deployment_excludes_local_sessions_and_credentials(tmp_path, monkeypatch):
    package = tmp_path / "helpdesk"
    for relative in (
        "__init__.py",
        "agent.py",
        "data/knowledge.json",
        "static/index.html",
        ".adk/session.db",
        ".adk/artifacts/private.txt",
        ".env",
        "__pycache__/agent.pyc",
    ):
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    monkeypatch.setattr("scripts.deploy_agent.ROOT", tmp_path)
    assert deployment_files() == [
        "helpdesk/__init__.py",
        "helpdesk/agent.py",
        "helpdesk/data/knowledge.json",
        "helpdesk/static/index.html",
    ]
