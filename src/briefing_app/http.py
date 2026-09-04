from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpFetchResult:
    status_code: int
    body: bytes
    headers: dict[str, str]
    url: str


class Fetcher(Protocol):
    def fetch(
        self, url: str, timeout_seconds: float, headers: dict[str, str]
    ) -> HttpFetchResult:
        ...


class UrlLibFetcher:
    def fetch(
        self, url: str, timeout_seconds: float, headers: dict[str, str]
    ) -> HttpFetchResult:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=timeout_seconds) as response:
            return HttpFetchResult(
                status_code=int(response.status),
                body=response.read(),
                headers=dict(response.headers.items()),
                url=response.geturl(),
            )
