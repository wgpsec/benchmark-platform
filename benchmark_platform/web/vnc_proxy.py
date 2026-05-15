"""Admin VNC reverse proxy for dockur/windows containers.

Proxies noVNC (HTTP + WebSocket) traffic through the platform server,
so no extra ports are exposed on the host. Admin manually enables/disables
via API; the proxy route only exists while enabled.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import httpx
from fastapi import APIRouter, WebSocket, Request
from fastapi.responses import Response

from benchmark_platform.utils.logger import get_logger

logger = get_logger(Path('logs/competition-platform-server-logs.jsonl'))

router = APIRouter()

# Active VNC proxies: benchmark_id → container_ip
_active_proxies: dict[str, str] = {}


def _get_container_ip(benchmark_id: str, runtime_dir: Path) -> str | None:
    """Find the DC container's IP for a given benchmark."""
    try:
        res = subprocess.run(
            ['docker', 'ps', '--filter', 'label=com.docker.compose.service=dc',
             '--format', '{{.ID}}'],
            capture_output=True, text=True, timeout=10,
        )
        if res.returncode != 0 or not res.stdout.strip():
            return None

        for container_id in res.stdout.strip().splitlines():
            inspect_res = subprocess.run(
                ['docker', 'inspect', '--format',
                 '{{index .Config.Labels "com.docker.compose.project.working_dir"}}||'
                 '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}',
                 container_id.strip()],
                capture_output=True, text=True, timeout=5,
            )
            if inspect_res.returncode != 0:
                continue
            parts = inspect_res.stdout.strip().split('||')
            if len(parts) != 2:
                continue
            working_dir, ips = parts
            if f'/{benchmark_id}/' in working_dir:
                ip = ips.strip().split()[0] if ips.strip() else ""
                if ip:
                    return ip
    except Exception as e:
        logger.error("failed to get container IP", benchmark_id=benchmark_id, error=str(e))
    return None


def get_active_proxies() -> dict[str, str]:
    """Return current active VNC proxy mappings."""
    return dict(_active_proxies)


def enable_vnc(benchmark_id: str, runtime_dir: Path) -> str | None:
    """Enable VNC proxy for a benchmark. Returns the proxy URL path or None on failure."""
    if benchmark_id in _active_proxies:
        return f"/admin/vnc/{benchmark_id}/"

    ip = _get_container_ip(benchmark_id, runtime_dir)
    if not ip:
        return None

    _active_proxies[benchmark_id] = ip
    logger.info("vnc proxy enabled", benchmark_id=benchmark_id, container_ip=ip)
    return f"/admin/vnc/{benchmark_id}/"


def disable_vnc(benchmark_id: str) -> None:
    """Disable VNC proxy for a benchmark."""
    if benchmark_id in _active_proxies:
        del _active_proxies[benchmark_id]
        logger.info("vnc proxy disabled", benchmark_id=benchmark_id)


@router.api_route("/admin/vnc/{benchmark_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def vnc_http_proxy(request: Request, benchmark_id: str, path: str = ""):
    """Reverse proxy HTTP requests to the noVNC container."""
    if benchmark_id not in _active_proxies:
        return Response(content="VNC proxy not enabled for this challenge", status_code=404)

    container_ip = _active_proxies[benchmark_id]
    target_url = f"http://{container_ip}:8006/{path}"
    if request.url.query:
        target_url += f"?{request.url.query}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        body = await request.body()
        headers = dict(request.headers)
        headers.pop("host", None)

        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=body,
            )
        except httpx.ConnectError:
            return Response(content="Cannot connect to VNC container", status_code=502)

        excluded_headers = {"transfer-encoding", "content-encoding", "content-length"}
        response_headers = {
            k: v for k, v in resp.headers.items()
            if k.lower() not in excluded_headers
        }
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=response_headers,
        )


@router.websocket("/admin/vnc/{benchmark_id}/{path:path}")
async def vnc_ws_proxy(websocket: WebSocket, benchmark_id: str, path: str = ""):
    """Reverse proxy WebSocket connections to the noVNC container."""
    if benchmark_id not in _active_proxies:
        await websocket.close(code=4004)
        return

    container_ip = _active_proxies[benchmark_id]
    ws_url = f"ws://{container_ip}:8006/{path}"
    if websocket.url.query:
        ws_url += f"?{websocket.url.query}"

    await websocket.accept()

    import websockets

    try:
        async with websockets.connect(ws_url) as upstream:
            async def client_to_upstream():
                try:
                    while True:
                        data = await websocket.receive()
                        if "text" in data:
                            await upstream.send(data["text"])
                        elif "bytes" in data:
                            await upstream.send(data["bytes"])
                except Exception:
                    pass

            async def upstream_to_client():
                try:
                    async for message in upstream:
                        if isinstance(message, str):
                            await websocket.send_text(message)
                        else:
                            await websocket.send_bytes(message)
                except Exception:
                    pass

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception as e:
        logger.error("vnc websocket proxy error", benchmark_id=benchmark_id, error=str(e))
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
