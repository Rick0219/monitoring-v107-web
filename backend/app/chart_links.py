"""Authenticated deep links. QR codes carry an address, never credentials."""
import ipaddress
import socket
from urllib.parse import urlencode
from app.core.config import settings


def lan_addresses():
    candidates = []
    # UDP connect selects the default route; no packet or user data is sent.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect(("8.8.8.8", 80))
            candidates.append(route.getsockname()[0])
    except OSError:
        pass
    try:
        candidates.extend(item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return list(dict.fromkeys(ip for ip in candidates if ipaddress.ip_address(ip).is_private
                             and not ipaddress.ip_address(ip).is_loopback
                             and not ipaddress.ip_address(ip).is_link_local
                             and not ipaddress.ip_address(ip).is_unspecified))


def make_chart_link(request, project_id, measurement_key):
    path = f"/charts/{project_id}?" + urlencode({"measurement": measurement_key})
    if settings.PUBLIC_BASE_URL:
        return {"url": settings.PUBLIC_BASE_URL + path, "network": "configured", "message": "扫码后登录当前工程创建人、成员或管理员账号。"}
    hostname = request.url.hostname or ""
    if hostname not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return {"url": str(request.base_url).rstrip("/") + path, "network": "current", "message": "使用当前网站地址，扫码后登录即可查看和修改图表。"}
    if settings.WEB_BIND_HOST in {"127.0.0.1", "localhost", "::1"}:
        return {"url": None, "network": "local_only", "message": "当前服务仅允许本机访问。关闭旧服务后双击 start.cmd，以局域网模式启动。"}
    addresses = lan_addresses()
    if not addresses:
        return {"url": None, "network": "unavailable", "message": "未找到局域网地址，请连接 Wi-Fi 或有线网络后刷新。"}
    port = request.url.port
    origin = f"{request.url.scheme}://{addresses[0]}" + (f":{port}" if port else "")
    return {"url": origin + path, "network": "lan", "message": "手机和电脑连接同一局域网；扫码后登录。电脑更换网络后请重新获取二维码。"}
