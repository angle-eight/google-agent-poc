"""Delete the specified agent and its managed child resources."""

import argparse

from helpdesk.config import RESOURCE_PATTERN, Settings


def main():
    parser = argparse.ArgumentParser(description="指定したAgent Runtimeとセッションを削除")
    parser.add_argument("resource_name", help="削除するエージェントの完全なリソース名")
    args = parser.parse_args()
    if not RESOURCE_PATTERN.fullmatch(args.resource_name):
        parser.error("完全なリソース名を指定してください。")
    settings = Settings.from_env()
    settings.require_cloud()
    from helpdesk.platform_client import Client

    client = Client(project=settings.project, location=settings.location)
    operation = client.agent_engines.delete(name=args.resource_name, force=True)
    print(f"削除を開始しました: {operation.name}")
    print("Google Cloudコンソールで完了を確認してください。")


if __name__ == "__main__":
    main()
