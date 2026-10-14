"""H3: profile data containing __IFACE__/__INTERFACE__ must render verbatim.

Only the template/code-owned sockopt.interface bindings get the alias.
"""
import json
from pathlib import Path

from xrayui.core import render
from xrayui.core.profiles import Profile

TEMPLATE = Path(__file__).resolve().parent.parent / "config.template.json"


def test_ws_path_with_placeholder_is_emitted_verbatim():
    p = Profile(name="srv", protocol="vless", address="203.0.113.1", port=443,
                id="u", network="ws", security="none", path="/__IFACE__/x")
    cfg = json.loads(render.build_text(p, "tun9", TEMPLATE))
    assert cfg["outbounds"][0]["streamSettings"]["wsSettings"]["path"] == "/__IFACE__/x"


def test_sni_host_and_name_with_placeholders_are_emitted_verbatim():
    p = Profile(name="__IFACE__-srv", protocol="vless", address="203.0.113.1",
                port=443, id="u", network="ws", security="tls",
                sni="__INTERFACE__.example.com", path="/x", host="__IFACE__")
    cfg = json.loads(render.build_text(p, "tun9", TEMPLATE))
    stream = cfg["outbounds"][0]["streamSettings"]
    assert stream["tlsSettings"]["serverName"] == "__INTERFACE__.example.com"
    assert stream["wsSettings"]["headers"] == {"Host": "__IFACE__"}


def test_interface_bindings_still_get_the_alias():
    p = Profile(name="srv", protocol="vless", address="203.0.113.1", port=443,
                id="u", network="ws", security="none", path="/__IFACE__/x")
    text = render.build_text(p, "tun9", TEMPLATE)
    cfg = json.loads(text)
    ifaces = [o["streamSettings"]["sockopt"]["interface"]
              for o in cfg["outbounds"] if "streamSettings" in o and "sockopt" in o["streamSettings"]]
    assert ifaces and all(i == "tun9" for i in ifaces)
    # The only remaining placeholder occurrence is the verbatim profile data.
    assert text.count("__IFACE__") == 1  # the ws path is untouched; nothing else leaks


def test_normal_profiles_render_byte_identical():
    # A profile without placeholder text must render exactly like the template
    # with the alias substituted (no behaviour change for normal profiles).
    from xrayui.core.importer import parse_vless
    sample = parse_vless(
        "vless://11111111-1111-1111-1111-111111111111@203.0.113.10:443"
        "?encryption=mlkem768x25519plus.native.0rtt.EXAMPLE_KEY"
        "&type=tcp&security=none#Sample")

    def _sub(obj, iface):
        if isinstance(obj, dict):
            return {k: _sub(v, iface) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sub(v, iface) for v in obj]
        if isinstance(obj, str):
            return obj.replace("__IFACE__", iface).replace("__INTERFACE__", iface)
        return obj

    expected = _sub(json.loads(TEMPLATE.read_text(encoding="utf-8")), "Wi-Fi")
    out = json.loads(render.build_text(sample, "Wi-Fi", TEMPLATE))

    def others(cfg):
        return ({k: v for k, v in cfg.items() if k != "outbounds"},
                [o for o in cfg["outbounds"] if o.get("tag") != "proxy"])
    assert others(out) == others(expected)
