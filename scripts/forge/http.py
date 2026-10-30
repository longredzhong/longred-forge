"""Bounded, redirect-aware HTTP reads; credentials never cross origins."""
import hashlib
import time
from typing import Callable, Mapping, Optional, TypeVar

import httpx

DEFAULT_HTTP_TIMEOUT = 30.0
ASSET_DOWNLOAD_TIMEOUT = 120.0
T = TypeVar("T")


class HTTPClient:
    def __init__(self, attempts: int = 3, max_redirects: int = 5,
                 transport=None, sleep: Callable[[float], None] = time.sleep):
        if not 1 <= attempts <= 10 or not 0 <= max_redirects <= 10:
            raise ValueError("HTTP retry/redirect bounds exceeded")
        self.attempts = attempts
        self.max_redirects = max_redirects
        self.transport = transport
        self.sleep = sleep

    def read(self, url: str, consume: Callable[[httpx.Response], T],
             headers: Optional[Mapping[str, str]] = None,
             timeout: float = DEFAULT_HTTP_TIMEOUT) -> T:
        original = httpx.URL(url)
        for attempt in range(self.attempts):
            retry_delay = min(2 ** attempt, 8)
            try:
                with httpx.Client(transport=self.transport, timeout=timeout,
                                  follow_redirects=False, trust_env=False) as client:
                    current = original
                    request_headers = dict(headers or {})
                    for redirect in range(self.max_redirects + 1):
                        if current.scheme != "https" or current.username or current.password:
                            raise ValueError("Only HTTPS upstream URLs without embedded credentials are allowed")
                        with client.stream("GET", current, headers=request_headers) as response:
                            if response.is_redirect:
                                if redirect == self.max_redirects:
                                    raise RuntimeError("Upstream redirect limit exceeded")
                                target = current.join(response.headers["location"])
                                if (target.scheme, target.host, target.port) != (current.scheme, current.host, current.port):
                                    request_headers = {k: v for k, v in request_headers.items()
                                                       if k.lower() in {"accept", "user-agent"}}
                                    client.cookies.clear()
                                current = target
                                continue
                            if response.status_code == 429 or response.status_code in {500, 502, 503, 504}:
                                delay = response.headers.get("retry-after", "")
                                if delay.isdigit():
                                    retry_delay = min(int(delay), 8)
                                response.raise_for_status()
                            response.raise_for_status()
                            return consume(response)
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                transient = isinstance(exc, httpx.TransportError) or exc.response.status_code in {429, 500, 502, 503, 504}
                if not transient or attempt + 1 == self.attempts:
                    raise
                self.sleep(retry_delay)
        raise RuntimeError("HTTP attempts exhausted")

    def json(self, url: str, headers=None):
        def decode(response):
            response.read()
            return response.json()
        return self.read(url, decode, headers)

    def text(self, url: str, headers=None) -> str:
        return self.read(url, lambda response: response.read().decode("utf-8"), headers)

    def sha256(self, url: str, headers=None) -> str:
        def digest(response):
            hasher = hashlib.sha256()
            for chunk in response.iter_bytes():
                hasher.update(chunk)
            return hasher.hexdigest()
        return self.read(url, digest, headers, ASSET_DOWNLOAD_TIMEOUT)
