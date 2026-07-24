"""Queue-on-sleep send/flush semantics (KPF 4) -- the primitive every send
path (service, raw upload, library send, scene send, schedule fire) funnels
through so a sleeping frame gets the image on wake instead of losing it or
double-sending.

Flagged as the most carefully-engineered, previously-untested mechanism in
the codebase: see coordinator.py's docstrings on async_send_image_or_queue /
_async_flush_pending_send for the exact contract being pinned down here.
"""

from __future__ import annotations

import base64

import aiohttp
import pytest
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def coordinator(make_coordinator, make_frame_entry):
    return make_coordinator(make_frame_entry())


async def test_immediate_success_returns_success_not_queued(coordinator, aioclient_mock):
    aioclient_mock.post(f"http://{coordinator.host}/api/image", status=200)

    result = await coordinator.async_send_image_or_queue(b"binary-image-data")

    assert result == {"success": True, "queued": False}
    assert coordinator.pending_send is None


async def test_connection_error_queues_the_send(coordinator, aioclient_mock):
    # Genuinely unreachable: the post-timeout /api/info probe fails too.
    aioclient_mock.post(f"http://{coordinator.host}/api/image", exc=aiohttp.ClientConnectionError())
    aioclient_mock.get(f"http://{coordinator.host}/api/info", exc=aiohttp.ClientConnectionError())

    result = await coordinator.async_send_image_or_queue(b"binary-image-data", image_id="img1")

    assert result == {"success": False, "queued": True}
    assert coordinator.pending_send is not None
    assert coordinator.pending_send["image_id"] == "img1"
    assert base64.b64decode(coordinator.pending_send["bin_b64"]) == b"binary-image-data"
    # Fast-poll kicks in while something is queued, so a woken frame gets
    # its image promptly instead of waiting the full scan_interval.
    from custom_components.digital_frames.coordinator import _FAST_POLL_INTERVAL

    assert coordinator.update_interval == _FAST_POLL_INTERVAL


async def test_timeout_also_queues_the_send(coordinator, aioclient_mock):
    # Genuinely unreachable: the post-timeout /api/info probe fails too.
    aioclient_mock.post(f"http://{coordinator.host}/api/image", exc=TimeoutError())
    aioclient_mock.get(f"http://{coordinator.host}/api/info", exc=TimeoutError())

    result = await coordinator.async_send_image_or_queue(b"data")

    assert result == {"success": False, "queued": True}


async def test_timeout_but_frame_answers_probe_is_not_queued(coordinator, aioclient_mock):
    # The 7.3in clone firmware blocks its HTTP response on the ~30s e-ink
    # redraw before answering, so a client-side timeout doesn't mean the
    # frame never got the image -- it may already be displaying it. If the
    # frame answers a follow-up /api/info right away, it's awake, so this
    # must NOT queue the same bytes for a later flush -- that would
    # guarantee a real duplicate redraw once the next poll delivers it.
    aioclient_mock.post(f"http://{coordinator.host}/api/image", exc=TimeoutError())
    aioclient_mock.get(f"http://{coordinator.host}/api/info", json={})

    result = await coordinator.async_send_image_or_queue(b"data", image_id="img1")

    assert result == {"success": True, "queued": False, "unconfirmed": True}
    assert coordinator.pending_send is None
    assert coordinator.last_image_id == "img1"
    from custom_components.digital_frames.coordinator import _FAST_POLL_INTERVAL

    assert coordinator.update_interval != _FAST_POLL_INTERVAL


async def test_rejected_response_raises_clean_error_and_clears_pending(
    coordinator, aioclient_mock
):
    """The frame was reached and definitively rejected the request (e.g. a
    malformed upload). Unlike a connection drop or timeout, retrying the
    identical payload from the queue would only fail again identically --
    this must not stay queued forever, and must surface as a clean
    HomeAssistantError rather than propagate the raw aiohttp exception
    (which used to reach the send_image/generate_ai_image services
    uncaught)."""
    aioclient_mock.post(f"http://{coordinator.host}/api/image", status=500)

    with pytest.raises(HomeAssistantError):
        await coordinator.async_send_image_or_queue(b"data", image_id="img1")

    assert coordinator.pending_send is None
    # Must not be left pinned to the fast-poll interval for a payload that
    # will never successfully flush.
    from custom_components.digital_frames.coordinator import _FAST_POLL_INTERVAL

    assert coordinator.update_interval != _FAST_POLL_INTERVAL


async def test_successful_poll_flushes_a_queued_send(coordinator, aioclient_mock):
    aioclient_mock.post(f"http://{coordinator.host}/api/image", exc=aiohttp.ClientConnectionError())
    aioclient_mock.get(f"http://{coordinator.host}/api/info", exc=aiohttp.ClientConnectionError())
    await coordinator.async_send_image_or_queue(b"data", image_id="img1")
    assert coordinator.pending_send is not None

    aioclient_mock.clear_requests()
    aioclient_mock.post(f"http://{coordinator.host}/api/image", status=200)
    aioclient_mock.get(f"http://{coordinator.host}/api/info", json={})

    await coordinator._async_update_data()
    # The flush is fired via hass.async_create_task from inside
    # _async_update_data -- let it run.
    await coordinator.hass.async_block_till_done()

    assert coordinator.pending_send is None
    assert coordinator.last_image_id == "img1"


async def test_restart_mid_queue_is_hydrated_from_store(
    hass, make_coordinator, make_frame_entry, hass_storage
):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    key = f"digital_frames_pending_send_{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "schema": 2,
            "token": "abc123",
            "bin_b64": base64.b64encode(b"queued-bytes").decode("ascii"),
            "image_id": "img-restart",
            "thumbnail_b64": None,
            "queued_at": 0,
        },
    }

    coordinator = make_coordinator(entry)
    await coordinator.async_load_pending_send()

    assert coordinator.pending_send is not None
    assert coordinator.pending_send["image_id"] == "img-restart"
    from custom_components.digital_frames.coordinator import _FAST_POLL_INTERVAL

    assert coordinator.update_interval == _FAST_POLL_INTERVAL


async def test_stale_schema_payload_is_discarded_on_load(
    hass, make_coordinator, make_frame_entry, hass_storage
):
    entry = make_frame_entry()
    entry.add_to_hass(hass)
    key = f"digital_frames_pending_send_{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        # No "schema" stamp at all -- written by a pre-v0.12.41 version.
        "data": {"bin_b64": "xxx", "image_id": "old"},
    }

    coordinator = make_coordinator(entry)
    await coordinator.async_load_pending_send()

    assert coordinator.pending_send is None


async def test_newer_send_supersedes_in_flight_older_one(coordinator, monkeypatch):
    # Simulate a slow first send: its network call hangs until released,
    # while a second (newer) send replaces pending_send in the meantime.
    # The first send's eventual completion must not clobber the newer
    # entry -- guarded by the token check in _clear_pending_if_current.
    import asyncio

    first_send_started = asyncio.Event()
    release_first_send = asyncio.Event()

    async def _slow_first_send(image_bytes):
        first_send_started.set()
        await release_first_send.wait()
        return 200

    monkeypatch.setattr(coordinator, "async_send_image", _slow_first_send)

    first_task = asyncio.ensure_future(
        coordinator.async_send_image_or_queue(b"first", image_id="first-img")
    )
    await first_send_started.wait()

    # A second, newer send is queued directly (as a real connection-error
    # send_image_or_queue call would do) while the first is still in flight.
    await coordinator._set_pending(
        {
            "schema": 2,
            "token": "newer-token",
            "bin_b64": "eA==",
            "image_id": "second-img",
            "thumbnail_b64": None,
            "queued_at": 0,
        }
    )

    release_first_send.set()
    await first_task

    # The first send's success calls _clear_pending_if_current(first_token),
    # which must be a no-op now that pending_send holds the newer entry.
    assert coordinator.pending_send is not None
    assert coordinator.pending_send["token"] == "newer-token"
    assert coordinator.pending_send["image_id"] == "second-img"


async def test_flush_failure_drops_pending_entry_without_retry(coordinator, monkeypatch):
    await coordinator._set_pending(
        {
            "schema": 2,
            "token": "tok",
            "bin_b64": base64.b64encode(b"data").decode("ascii"),
            "image_id": "img1",
            "thumbnail_b64": None,
            "queued_at": 0,
        }
    )

    async def _fail(image_bytes):
        raise aiohttp.ClientConnectionError()

    monkeypatch.setattr(coordinator, "async_send_image", _fail)

    await coordinator._async_flush_pending_send()

    # Dropped, not retried -- a retry could double-draw a panel that
    # actually already displayed the image before timing out (see the
    # docstring on _async_flush_pending_send).
    assert coordinator.pending_send is None


async def test_async_send_image_uses_240s_timeout(coordinator, monkeypatch):
    import aiohttp
    from unittest.mock import AsyncMock, MagicMock

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.raise_for_status = MagicMock()

    class MockAsyncContextManager:
        async def __aenter__(self):
            return mock_response
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    captured_kwargs = {}
    def fake_post(url, **kwargs):
        nonlocal captured_kwargs
        captured_kwargs = kwargs
        return MockAsyncContextManager()

    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    session = async_get_clientsession(coordinator.hass)
    monkeypatch.setattr(session, "post", fake_post)

    await coordinator.async_send_image(b"test-bytes")

    assert "timeout" in captured_kwargs
    assert isinstance(captured_kwargs["timeout"], aiohttp.ClientTimeout)
    assert captured_kwargs["timeout"].total == 240

