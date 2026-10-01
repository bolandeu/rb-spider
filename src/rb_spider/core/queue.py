"""The crawl queue Crawlee pulls from: pending URLs in memory, a `Request` only while one is in flight.

Crawlee's own memory queue keeps every `Request` it was given, handled or not, at ~2 KB each — a
100k-URL crawl spent ~250 MB on it. Here a pending URL is a `(url, check)` tuple, a `Request` is built
when Crawlee asks for the next URL and forgotten once it is handled. Deciding what to enqueue (seen
URLs, scope, limits) and keeping the queue durable (the `frontier` table) is the crawl's job, not
the queue's — see `crawl._run`.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable, Sequence
from datetime import timedelta

from crawlee import Request
from crawlee.request_loaders import RequestManager
from crawlee.storage_clients.models import ProcessedRequest


class MemoryQueue(RequestManager):
    def __init__(self, make_request: Callable[[str, bool], Request]) -> None:
        self._make_request = make_request
        self._pending: deque[tuple[str, bool] | Request] = deque()
        self._in_flight = 0
        self._handled = 0
        self._waiting = 0  # URLs put back after a pause (push_later), not due yet

    def push(self, url: str, check: bool) -> None:
        """Enqueue a URL the crawl has admitted; `check` — status only, the body isn't read."""
        self._pending.append((url, check))

    def push_later(self, url: str, check: bool, delay_s: float) -> None:
        """Enqueue a URL after `delay_s` seconds; the crawl isn't finished while it waits. A timer, not a sleep in
        the caller: Crawlee calls the failed-request handler of a timed-out request in a cancelled task."""

        def due() -> None:
            self._waiting -= 1
            self.push(url, check)

        self._waiting += 1
        asyncio.get_running_loop().call_later(delay_s, due)

    async def add_request(self, request: str | Request, *, forefront: bool = False) -> ProcessedRequest:
        request = self._transform_request(request)
        if forefront:
            self._pending.appendleft(request)
        else:
            self._pending.append(request)
        return ProcessedRequest(unique_key=request.unique_key, was_already_present=False, was_already_handled=False)

    async def add_requests(
        self,
        requests: Sequence[str | Request],
        *,
        forefront: bool = False,
        batch_size: int = 1000,  # the signature Crawlee calls with
        wait_time_between_batches: timedelta = timedelta(seconds=1),
        wait_for_all_requests_to_be_added: bool = False,
        wait_for_all_requests_to_be_added_timeout: timedelta | None = None,
    ) -> None:
        for request in requests:
            await self.add_request(request, forefront=forefront)

    async def fetch_next_request(self) -> Request | None:
        if not self._pending:
            return None
        item = self._pending.popleft()
        self._in_flight += 1
        return item if isinstance(item, Request) else self._make_request(*item)

    async def mark_request_as_handled(self, request: Request) -> ProcessedRequest:
        self._in_flight -= 1
        self._handled += 1
        return ProcessedRequest(unique_key=request.unique_key, was_already_present=True, was_already_handled=True)

    async def reclaim_request(self, request: Request, *, forefront: bool = False) -> ProcessedRequest:
        """A failed request goes back for a retry — as the `Request` itself: it carries the retry count."""
        self._in_flight -= 1
        return await self.add_request(request, forefront=forefront)

    async def is_empty(self) -> bool:
        return not self._pending

    async def is_finished(self) -> bool:
        return not self._pending and not self._in_flight and not self._waiting

    async def get_handled_count(self) -> int:
        return self._handled

    async def get_total_count(self) -> int:
        return self._handled + self._in_flight + len(self._pending) + self._waiting

    async def drop(self) -> None:
        self._pending.clear()
