"""Concurrent frame polling/sends -- the nearest equivalent this
`iot_class: local_polling` integration has to a "load" test.

There's no prod-traffic concept for a locally-polled HA integration (see
TESTING_STRATEGY.md's rationale for not running K6-style load tests), but a
household with several frames does poll/send concurrently for real, and
each coordinator's state (pending_send, consecutive-failure counter) must
stay isolated per frame instead of racing on shared module-level state.
"""

from __future__ import annotations

import asyncio

import aiohttp


async def test_n_frames_poll_concurrently_without_cross_talk(
    hass, make_coordinator, make_frame_entry, aioclient_mock
):
    coordinators = [
        make_coordinator(make_frame_entry(host=f"192.168.1.{50 + i}", entry_id=f"entry-{i}"))
        for i in range(8)
    ]
    for i, coord in enumerate(coordinators):
        if i % 2 == 0:
            aioclient_mock.get(f"http://{coord.host}/api/info", json={"battery": i})
        else:
            aioclient_mock.get(f"http://{coord.host}/api/info", exc=aiohttp.ClientConnectionError())

    async def _poll(coord, index):
        if index % 2 == 0:
            data = await coord._async_update_data()
            assert data["battery"] == index
            assert coord._consecutive_failures == 0
        else:
            from homeassistant.helpers.update_coordinator import UpdateFailed

            try:
                await coord._async_update_data()
                raise AssertionError("expected UpdateFailed")
            except UpdateFailed:
                pass
            assert coord._consecutive_failures == 1

    await asyncio.gather(*(_poll(c, i) for i, c in enumerate(coordinators)))


async def test_n_concurrent_sends_to_distinct_frames_stay_isolated(
    hass, make_coordinator, make_frame_entry, aioclient_mock
):
    coordinators = [
        make_coordinator(make_frame_entry(host=f"192.168.1.{70 + i}", entry_id=f"send-entry-{i}"))
        for i in range(6)
    ]
    for coord in coordinators:
        aioclient_mock.post(f"http://{coord.host}/api/image", status=200)

    results = await asyncio.gather(
        *(
            c.async_send_image_or_queue(f"payload-{i}".encode(), image_id=f"img-{i}")
            for i, c in enumerate(coordinators)
        )
    )

    assert all(r == {"success": True, "queued": False} for r in results)
    for i, coord in enumerate(coordinators):
        assert coord.last_image_id == f"img-{i}"
        assert coord.pending_send is None
