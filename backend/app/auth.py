"""认证：HMAC 签名的 HttpOnly Cookie（替代 query token 传 SSE）。

登录接口用 X-API-Token 校验后签发 cookie；后续请求（含 EventSource）自动携带。
Cookie 格式：base64(payload).hexsig，payload = {"exp": <unix ts>}。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _sign(payload_b64: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()


def issue_auth_cookie(secret: str, ttl: int = 86400) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + ttl}).encode()
    ).decode().rstrip("=")
    return f"{payload}.{_sign(payload, secret)}"


def verify_auth_cookie(cookie_value: str, secret: str) -> bool:
    try:
        payload_b64, sig = cookie_value.rsplit(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(_sign(payload_b64, secret), sig):
        return False
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded))
        return int(data.get("exp", 0)) > time.time()
    except Exception:  # noqa: BLE001 —— 任何解析失败都视为无效
        return False
