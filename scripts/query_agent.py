"""Smoke-test local Gemini or a deployed Agent Runtime from the CLI."""

import argparse
import asyncio
import json
from uuid import uuid4

from helpdesk.config import Settings
from helpdesk.service import create_service


async def query(args):
    service = await asyncio.to_thread(create_service, Settings.from_env())
    async with asyncio.timeout(120):
        result = await service.chat(args.user_id, args.message, args.session_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="現在のAPP_BACKENDに質問を送信")
    parser.add_argument("message")
    parser.add_argument("--user-id", default=f"cli-{uuid4().hex}")
    parser.add_argument("--session-id", help="会話を継続。前回と同じ --user-id も指定してください")
    args = parser.parse_args()
    asyncio.run(query(args))


if __name__ == "__main__":
    main()
