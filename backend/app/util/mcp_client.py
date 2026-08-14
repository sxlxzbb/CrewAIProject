"""MCP 客户端封装：对接 Java Spring AI MCP 服务（StreamableHTTP）。

注意：实测 mcp Python SDK 底层的 httpx 传输访问该服务会返回 502，
因此这里直接用 requests 实现 Streamable HTTP 的 JSON-RPC 交互，
不依赖 mcp SDK 的 HTTP 传输层。服务端为无状态模式（不下发 session-id），
每次请求独立携带鉴权头即可。

服务地址与鉴权从 settings 注入（.env 的 MCP_BASE_URL / MCP_AUTH_TOKEN）。
"""
import json

import requests

from app.config.settings import settings
from app.util.logger import get_logger

logger = get_logger("mcp")

# 工具名（由 Java 服务端声明，tools/list 可校验）
PUBLISH_TOOL = "publishWithObject"


class McpError(RuntimeError):
    pass


def _post(method: str, params: dict = None, _id: int = 1, session_id: str = None) -> dict:
    """发送一个 JSON-RPC 请求，返回 result 字典；出错抛 McpError。"""
    url = settings.mcp_base_url
    if not url:
        raise RuntimeError("MCP_BASE_URL 未配置")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Basic {settings.mcp_auth_token}" if settings.mcp_auth_token else "",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    payload = {"jsonrpc": "2.0", "id": _id, "method": method}
    if params is not None:
        payload["params"] = params

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    if resp.status_code >= 400:
        raise McpError(f"MCP HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    if "error" in data:
        raise McpError(f"MCP error {data['error']}")
    return data.get("result", {})


def list_tools() -> list:
    """列出服务端所有工具，返回原始工具定义列表。"""
    result = _post("tools/list", {}, _id=1)
    return result.get("tools", [])


def publish_article(article) -> dict:
    """调用 publishWithObject 发布一篇文章。

    article: ArticleOutput 实例（含 title/summary/body/keywords）。
    入参结构（按 MCP 端 schema，嵌套 article 对象）：
        {"article": {"title": "...", "summary": "...", "content": "...", "keywords": "..."}}
    keywords 由 list[str] 以顿号拼接成字符串传入。
    返回 MCP 工具调用的 result。
    """
    if isinstance(getattr(article, "keywords", None), list):
        keywords_str = "、".join(article.keywords)
    else:
        keywords_str = str(getattr(article, "keywords", "") or "")

    arguments = {
        "article": {
            "title": article.title or "",
            "summary": article.summary or "",
            "content": article.body or "",
            "keywords": keywords_str,
        }
    }
    logger.info(f"[mcp] 调用 {PUBLISH_TOOL}, title={article.title}")

    params = {"name": PUBLISH_TOOL, "arguments": arguments}
    result = _post("tools/call", params, _id=2)
    return result
