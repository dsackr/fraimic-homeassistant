"""Google Drive OAuth callback view (KPF 9): the ``error``/status message it
renders comes straight from the redirect's query string on a view that must
stay unauthenticated (no Authorization header on a plain browser redirect).

If this silently breaks: a crafted ``?error=`` value in the redirect URL
executes as script in the HA origin for anyone who opens it, pre-auth.
"""

from __future__ import annotations

from custom_components.digital_frames.library_http import (
    DigitalFramesLibraryGoogleOAuthCallbackView,
)


def test_page_escapes_html_in_message():
    payload = "<script>alert(1)</script>"
    resp = DigitalFramesLibraryGoogleOAuthCallbackView._page(
        f"Google declined: {payload}", ok=False
    )
    body = resp.body.decode("utf-8")
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_page_renders_plain_message_unescaped_by_caller():
    resp = DigitalFramesLibraryGoogleOAuthCallbackView._page(
        "Google Drive connected!", ok=True
    )
    body = resp.body.decode("utf-8")
    assert "Google Drive connected!" in body
    assert resp.status == 200
