"""도구 함수를 Agent SDK in-process MCP 서버 `planner`로 노출한다 (ADR 0005)."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server

from my_planner.domain import RunContext

SERVER_NAME = "planner"

# 두뇌가 부를 수 있는 도구 이름. 티켓마다 늘어난다(티켓 01에서는 비어 있다).
TOOL_NAMES: list[str] = []


def allowed_tool_patterns() -> list[str]:
    return [f"mcp__{SERVER_NAME}__*"]


def build_planner_server(tools: Any, ctx: RunContext) -> McpSdkServerConfig:
    """호출마다 새로 만든다. `ctx`는 도구 핸들러의 클로저로 넘긴다."""
    handlers: list[Any] = []  # 티켓 03부터 `tools`와 `ctx`를 감싼 핸들러가 들어온다
    return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=handlers)
