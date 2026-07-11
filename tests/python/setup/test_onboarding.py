"""First-run onboarding wizard's server-side completion flag (KPF 24).

If this silently breaks: the wizard reappears every session for every
admin, or one admin's skip doesn't stick for others.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from custom_components.fraimic.const import DOMAIN
from custom_components.fraimic.http_api import FraimicOnboardingView


class _FakeRequest:
    def __init__(self, hass, is_admin: bool = True):
        self.app = {"hass": hass}
        self._is_admin = is_admin

    def __getitem__(self, key):
        if key == "hass_user":
            return SimpleNamespace(is_admin=self._is_admin)
        raise KeyError(key)


def _body(response) -> dict:
    return json.loads(response.body)


async def test_get_default_is_incomplete(hass):
    view = FraimicOnboardingView()
    response = await view.get(_FakeRequest(hass))
    assert _body(response) == {"complete": False}


async def test_post_marks_complete(hass):
    view = FraimicOnboardingView()
    response = await view.post(_FakeRequest(hass, is_admin=True))
    assert response.status == 200
    assert _body(response) == {"success": True, "complete": True}

    get_response = await view.get(_FakeRequest(hass))
    assert _body(get_response) == {"complete": True}


async def test_post_rejected_for_non_admin(hass):
    view = FraimicOnboardingView()
    response = await view.post(_FakeRequest(hass, is_admin=False))
    assert response.status == 403

    # Must not have persisted -- still incomplete afterward.
    get_response = await view.get(_FakeRequest(hass))
    assert _body(get_response) == {"complete": False}


async def test_completion_persists_across_store_reload(hass):
    view = FraimicOnboardingView()
    await view.post(_FakeRequest(hass, is_admin=True))

    # Simulate a restart: drop the cached Store instance so the next call
    # reloads from the underlying (PHACC-mocked) storage backend rather
    # than an in-memory attribute.
    hass.data[DOMAIN].pop("_onboarding_store", None)

    response = await view.get(_FakeRequest(hass))
    assert _body(response) == {"complete": True}
