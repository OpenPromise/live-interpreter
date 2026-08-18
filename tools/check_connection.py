"""连通性检查：连接百炼翻译会话，确认 Key / 业务空间 ID / 模型可用。"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
import websockets


def _setup_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


async def main() -> None:
    load_dotenv()
    api_key = os.getenv("DASHSCOPE_API_KEY")
    workspace_id = os.getenv("QWEN_WORKSPACE_ID")
    region = os.getenv("QWEN_REGION", "cn-beijing")
    model = os.getenv("QWEN_MODEL", "qwen3.5-livetranslate-flash-realtime")
    if not api_key or not workspace_id:
        print("缺少 DASHSCOPE_API_KEY 或 QWEN_WORKSPACE_ID，请先配置 .env")
        sys.exit(2)

    url = os.getenv("QWEN_WS_URL") or (
        f"wss://{workspace_id}.{region}.maas.aliyuncs.com"
        f"/api-ws/v1/realtime?model={model}"
    )
    print(f"连接: {url}")
    try:
        ws = await websockets.connect(
            url,
            additional_headers={"Authorization": f"Bearer {api_key}"},
            max_size=16 * 1024 * 1024,
        )
    except websockets.exceptions.InvalidStatus as exc:
        body = (
            bytes(exc.response.body).decode("utf-8", errors="replace")
            if exc.response.body
            else ""
        )
        print(f"连接被拒绝: HTTP {exc.response.status_code}")
        if body:
            print(f"服务端信息: {body}")
            if "IllegalEndpoint" in body:
                print("提示：业务空间专属域名无效，可在 .env 设置 QWEN_WS_URL 使用公共域名：")
                print(
                    f"  wss://dashscope.aliyuncs.com/api-ws/v1/realtime?model={model}"
                )
        sys.exit(1)
    except Exception as exc:
        print(f"连接失败: {type(exc).__name__}: {exc}")
        sys.exit(1)

    await ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "input_audio_format": "pcm",
                    "output_audio_format": "pcm",
                    "translation": {"language": "zh"},
                },
            }
        )
    )
    print("已发送 session.update，等待服务端事件（最多 8 秒）...")
    saw_event = False
    try:
        async with asyncio.timeout(8):
            async for raw in ws:
                ev = json.loads(raw)
                saw_event = True
                print(f"收到事件: {ev.get('type')} {json.dumps(ev, ensure_ascii=False)[:400]}")
                if ev.get("type") == "session.error":
                    break
    except TimeoutError:
        pass
    finally:
        await ws.close()

    if saw_event:
        print("连通正常：服务端有响应。")
    else:
        print("连接建立但 8 秒内没有事件（可能正常，正式跑一次便知）。")


if __name__ == "__main__":
    _setup_stdio()
    asyncio.run(main())
