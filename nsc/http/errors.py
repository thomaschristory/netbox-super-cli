"""HTTP error types raised by NetBoxClient."""

from __future__ import annotations


class NetBoxAPIError(Exception):
    """A non-2xx response from NetBox."""

    def __init__(
        self,
        status_code: int,
        url: str,
        body_snippet: str,
        headers: dict[str, str],
    ) -> None:
        super().__init__(f"NetBox API {status_code} on {url}")
        self.status_code = status_code
        self.url = url
        self.body_snippet = body_snippet
        self.headers = headers

    def render_for_cli(self) -> str:
        return f"NetBox API {self.status_code} on {self.url}: {self.body_snippet}"


class NetBoxClientError(Exception):
    """A transport-level failure reaching NetBox (DNS, TCP, TLS, timeout)."""

    def __init__(self, url: str, cause: BaseException) -> None:
        super().__init__(f"NetBox transport error on {url}: {cause}")
        self.url = url
        self.cause = cause

    def render_for_cli(self) -> str:
        return f"NetBox transport error on {self.url}: {self.cause}"
