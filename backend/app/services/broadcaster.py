import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

QUEUE_SIZE = 500


class Broadcaster:
    """Fan-out of server-sent events to every connected /stream subscriber.

    Decisions are produced on worker threads (sync routes, replay workers), so publishing hops onto the
    event loop with call_soon_threadsafe. A slow subscriber loses its oldest events instead of blocking scoring.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[tuple[str, str]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def subscribers(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[tuple[str, str]]:
        q: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=QUEUE_SIZE)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: str, data_json: str) -> None:
        """Thread-safe. `data_json` is an already-serialised JSON document."""
        if self._loop is None or not self._subscribers:
            return
        try:
            self._loop.call_soon_threadsafe(self._fan_out, event, data_json)
        except RuntimeError:  # loop closed during shutdown
            pass

    def _fan_out(self, event: str, data_json: str) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            if q.full():
                q.get_nowait()  # drop oldest
            q.put_nowait((event, data_json))
