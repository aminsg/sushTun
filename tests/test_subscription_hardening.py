"""Hardening for subscription fetching and stored-subscription parsing.

H2: fetch()/refresh()/_default_fetch() must only speak http(s) -- the app
runs as root, so a file:// URL from a hand-edited subscriptions.json must
never make it read local files. Redirects must not hop schemes either.

H4: from_dict() must coerce hostile JSON types to safe defaults so is_due()
never raises on a stored entry.

T1: SubscriptionEditDialog must reject non-http(s) URLs like it already
rejects bad regexes.
"""
from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from xrayui.core import routing_io, subscription
from xrayui.core.subscription import Subscription


def _fail_if_network(req, timeout=None):
    raise AssertionError(f"must be rejected before any fetch: {req!r}")


# -- H2: scheme allowlist ----------------------------------------------------
@pytest.mark.parametrize("url", [
    "file:///etc/hostname",
    "FILE:///etc/hostname",
    "ftp://example.com/sub.txt",
    "gopher://example.com/sub",
    "not a url",
    "",
    "http://",
    "https://",
])
def test_fetch_rejects_non_http_urls_before_any_network(monkeypatch, url):
    monkeypatch.setattr(subscription.urllib.request, "urlopen", _fail_if_network)
    with pytest.raises(ValueError, match="http"):
        subscription.fetch(url)


def test_refresh_rejects_non_http_url_without_fetching(monkeypatch, tmp_path):
    monkeypatch.setattr(subscription.paths, "base_dir", lambda: tmp_path)
    monkeypatch.setattr(subscription, "fetch", _fail_if_network)
    from xrayui.core.profiles import ProfileStore
    sub = Subscription(url="file:///etc/hostname")
    with pytest.raises(ValueError, match="http"):
        subscription.refresh(sub, ProfileStore(), subscription.SubscriptionStore())


def test_default_fetch_rejects_non_http_urls(monkeypatch):
    monkeypatch.setattr(routing_io.urllib.request, "urlopen", _fail_if_network)
    with pytest.raises(ValueError, match="http"):
        routing_io._default_fetch("file:///etc/hostname")


class _SchemeHopHandler(BaseHTTPRequestHandler):
    target = "file:///etc/hostname"

    def do_GET(self):  # noqa: N802
        body = b"redirecting"
        self.send_response(302)
        self.send_header("Location", self.target)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve_hop(target):
    _SchemeHopHandler.target = target
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SchemeHopHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_http_only_redirect_handler_refuses_foreign_schemes():
    import urllib.request

    handler = subscription._HttpOnlyRedirectHandler()
    req = urllib.request.Request("https://example.com/sub")
    for bad in ("file:///etc/hostname", "ftp://example.com/sub",
                "gopher://example.com/sub"):
        with pytest.raises(ValueError, match="(?i)(http|redirect)"):
            handler.redirect_request(req, None, 302, "Found", {}, bad)
    # http(s) hops still pass through to the default handling (relative
    # ones are resolved to absolute by http_error_302 before they get here).
    for ok in ("https://example.com/other", "http://example.com/other"):
        assert handler.redirect_request(req, None, 302, "Found", {}, ok) is not None


@pytest.mark.parametrize("target_attr", ["file_target", "ftp_target"])
def test_fetch_refuses_a_redirect_to_a_non_http_scheme(tmp_path, target_attr):
    # The stdlib refuses some schemes itself (HTTPError) and lets others
    # through to the app's redirect handler (ValueError) -- either way the
    # file must never be read and the fetch must fail loudly.
    if target_attr == "file_target":
        decoy = tmp_path / "secret.txt"
        decoy.write_text(
            "vless://11111111-1111-1111-1111-111111111111@203.0.113.9:443#leaked\n")
        target = decoy.as_uri()
    else:
        target = "ftp://127.0.0.1:21/sub.txt"
    server, thread = _serve_hop(target)
    try:
        url = f"http://127.0.0.1:{server.server_port}/sub"
        with pytest.raises((ValueError, OSError), match="(?i)(http|redirect)"):
            subscription.fetch(url, timeout=5)
    finally:
        server.shutdown()
        thread.join()


def test_subscription_body_over_the_cap_is_refused(monkeypatch):
    class FakeResp:
        headers = {}

        def read(self, size=-1):
            return b"x" * (subscription.MAX_BODY_BYTES + 1)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(subscription.urllib.request, "urlopen",
                        lambda req, timeout=20.0: FakeResp())
    with pytest.raises(ValueError, match="too large"):
        subscription.fetch("https://sub.example/x")


def test_default_fetch_caps_the_body(monkeypatch):
    class FakeResp:
        headers = {}

        def read(self, size=-1):
            return b"x" * (subscription.MAX_BODY_BYTES + 1)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(routing_io.urllib.request, "urlopen",
                        lambda req, timeout=20.0: FakeResp())
    with pytest.raises(ValueError, match="too large"):
        routing_io._default_fetch("https://example.invalid/rules.json")


# -- H4: from_dict coercion ----------------------------------------------------
HOSTILE_NUMERICS = [
    ({"auto_update_hours": "5"}, 0),
    ({"auto_update_hours": [1]}, 0),
    ({"auto_update_hours": None}, 0),
    ({"auto_update_hours": True}, 0),
    ({"auto_update_hours": 999}, 168),
    ({"auto_update_hours": -3}, 0),
    ({"updated": "yesterday"}, 0.0),
    ({"updated": None}, 0.0),
    ({"updated": [1]}, 0.0),
]


@pytest.mark.parametrize("hostile, _expected", HOSTILE_NUMERICS)
def test_from_dict_hostile_numerics_never_break_is_due(hostile, _expected):
    base = {"url": "https://example.com/sub", "updated": 0.0}
    base.update(hostile)
    sub = Subscription.from_dict(base)
    # Must not raise (this used to kill auto-refresh for every subscription).
    assert isinstance(subscription.is_due(sub, 0, 9_999_999_999.0), bool)


@pytest.mark.parametrize("hostile, expected", HOSTILE_NUMERICS)
def test_from_dict_coerces_hostile_numerics_to_defaults(hostile, expected):
    base = {"url": "https://example.com/sub", "updated": 0.0}
    base.update(hostile)
    sub = Subscription.from_dict(base)
    key = next(iter(hostile))
    assert getattr(sub, key) == expected


def test_from_dict_clamps_auto_update_hours_to_the_ui_range():
    sub = Subscription.from_dict({"url": "https://example.com/sub",
                                  "auto_update_hours": 1000})
    assert sub.auto_update_hours == 168
    sub = Subscription.from_dict({"url": "https://example.com/sub",
                                  "auto_update_hours": 24})
    assert sub.auto_update_hours == 24


def test_from_dict_coerces_usage_and_collection_fields():
    sub = Subscription.from_dict({
        "url": "https://example.com/sub",
        "usage": {"upload": "lots", "download": None, "total": [1], "expire": "soon"},
        "profile_uids": ["ok", 1, None],
        "enabled": "yes",
        "uid": 123,
        "name": ["not", "a", "name"],
        "name_filter": None,
        "user_agent": 5,
    })
    assert (sub.usage.upload, sub.usage.download,
            sub.usage.total, sub.usage.expire) == (0, 0, 0, 0)
    assert sub.usage.used == 0
    assert sub.profile_uids == ["ok"]
    assert sub.enabled is True
    assert isinstance(sub.uid, str) and sub.uid
    assert sub.name == "Subscription"
    assert sub.name_filter == ""
    assert sub.user_agent == ""


def test_from_dict_rejects_a_string_profile_uid_list():
    # list("abc") would be ["a", "b", "c"] -- never treat a bare string as uids.
    sub = Subscription.from_dict({"url": "https://example.com/sub",
                                  "profile_uids": "abc"})
    assert sub.profile_uids == []


# -- T1: edit dialog URL validation -------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("url", ["not a url", "ftp://example.com/sub", "file:///etc/hostname",
                                 "http://", "https://", "example.com/sub"])
def test_subscription_dialog_rejects_non_http_urls(qapp, monkeypatch, url):
    from PySide6.QtWidgets import QDialog

    from xrayui.ui.dialogs import SubscriptionEditDialog
    warnings = []
    monkeypatch.setattr("xrayui.ui.dialogs.QMessageBox.warning",
                        lambda *a, **k: warnings.append(a))
    sub = Subscription(name="Main", url="https://example.com/old")
    dlg = SubscriptionEditDialog(sub)
    try:
        dlg.f_url.setText(url)
        dlg._save()
        assert warnings, f"no warning for {url!r}"
        assert dlg.result() != QDialog.Accepted, "dialog must stay open"
        assert sub.url == "https://example.com/old"
    finally:
        dlg.close()


def test_subscription_dialog_accepts_an_https_url(qapp):
    from PySide6.QtWidgets import QDialog

    from xrayui.ui.dialogs import SubscriptionEditDialog
    sub = Subscription(name="Main", url="")
    dlg = SubscriptionEditDialog(sub)
    try:
        dlg.f_url.setText("https://example.com/sub")
        dlg._save()
        assert dlg.result() == QDialog.Accepted
        assert sub.url == "https://example.com/sub"
    finally:
        dlg.close()


def test_from_dict_keeps_valid_values_untouched():
    sub = Subscription.from_dict({
        "url": "https://example.com/sub", "name": "Mine", "updated": 123.0,
        "profile_uids": ["a"], "uid": "u1", "enabled": False,
        "auto_update_hours": 24, "name_filter": "DE|NL",
        "user_agent": "Mine/1.0",
        "usage": {"upload": 1, "download": 2, "total": 10, "expire": 99},
    })
    assert (sub.url, sub.name, sub.updated) == ("https://example.com/sub", "Mine", 123.0)
    assert sub.profile_uids == ["a"] and sub.uid == "u1"
    assert sub.enabled is False and sub.auto_update_hours == 24
    assert sub.name_filter == "DE|NL" and sub.user_agent == "Mine/1.0"
    assert (sub.usage.upload, sub.usage.download,
            sub.usage.total, sub.usage.expire) == (1, 2, 10, 99)
