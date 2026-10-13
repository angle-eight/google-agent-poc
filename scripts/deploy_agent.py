"""Deploy an ADK application using the installed Agent Platform SDK."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from helpdesk.config import RESOURCE_PATTERN, Settings

ROOT = Path(__file__).resolve().parents[1]


def deployment_files() -> list[str]:
    """Upload application files explicitly, excluding ADK Web's local session storage."""
    package = ROOT / "helpdesk"
    files = [
        *package.glob("*.py"),
        *(package / "data").glob("*.json"),
        *(package / "static").glob("*"),
    ]
    return sorted(path.relative_to(ROOT).as_posix() for path in files if path.is_file())


def deployment_config(settings: Settings, display_name: str) -> dict:
    requirements = [
        f"google-cloud-aiplatform[agent_engines,adk]=={version('google-cloud-aiplatform')}",
        f"google-adk=={version('google-adk')}",
        f"google-genai=={version('google-genai')}",
        f"cloudpickle=={version('cloudpickle')}",
        f"pydantic=={version('pydantic')}",
        f"python-dotenv=={version('python-dotenv')}",
    ]
    config = {
        "display_name": display_name,
        "description": "Japanese helpdesk PoC with fictional policy search and purchase tools.",
        "requirements": requirements,
        "extra_packages": deployment_files(),
        "staging_bucket": settings.staging_bucket,
        "gcs_dir_name": f"helpdesk/{uuid4().hex}",
        "agent_framework": "google-adk",
        "env_vars": {
            "GOOGLE_GENAI_USE_VERTEXAI": "true",
            "GEMINI_MODEL": settings.model,
            "MODEL_LOCATION": settings.model_location,
        },
        "labels": {"purpose": "poc", "app": "helpdesk"},
        "min_instances": 0,
        "max_instances": 2,
    }
    if settings.service_account:
        config["service_account"] = settings.service_account
    return config


def main():
    parser = argparse.ArgumentParser(description="社内ヘルプデスクをAgent Runtimeへデプロイ")
    parser.add_argument("--display-name", default="helpdesk-agent-poc")
    parser.add_argument("--update", metavar="RESOURCE_NAME", help="既存リソースを更新")
    parser.add_argument(
        "--dry-run", action="store_true", help="設定のみ表示。クラウドには接続しない"
    )
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.update and not RESOURCE_PATTERN.fullmatch(args.update):
        parser.error("--update には完全なリソース名を指定してください。")
    config = deployment_config(settings, args.display_name)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "project": settings.project,
                    "location": settings.location,
                    "update": args.update,
                    "config": config,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    settings.require_cloud()
    if (
        not settings.staging_bucket.startswith("gs://")
        or "your-project-id" in settings.staging_bucket
    ):
        parser.error("GOOGLE_CLOUD_STAGING_BUCKET に作成済みの gs://バケット名を設定してください。")
    if Path.cwd() != ROOT:
        parser.error("リポジトリのルートディレクトリから実行してください。")

    import vertexai
    from vertexai.agent_engines import AdkApp

    from helpdesk.agent import create_agent
    from helpdesk.platform_client import AgentEngineConfig, Client

    vertexai.init(project=settings.project, location=settings.location)
    agent = AdkApp(agent=create_agent(settings.model, settings.model_location, settings.project))
    client = Client(project=settings.project, location=settings.location)
    cloud_config = AgentEngineConfig(**config)
    if args.update:
        remote = client.agent_engines.update(name=args.update, agent=agent, config=cloud_config)
    else:
        remote = client.agent_engines.create(agent=agent, config=cloud_config)
    api_resource = remote.api_resource
    if api_resource is None or not api_resource.name:
        raise RuntimeError("デプロイ結果のエージェントリソース名を取得できませんでした。")
    resource_name = api_resource.name
    result = {
        "resource_name": resource_name,
        "project": settings.project,
        "location": settings.location,
        "model": settings.model,
    }
    output = ROOT / ".deploy" / "agent.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"デプロイ結果: {output}")
    print(f"AGENT_ENGINE_RESOURCE_NAME={resource_name}")


if __name__ == "__main__":
    main()
