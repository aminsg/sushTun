"""T2-RV3: simple-mode bypass lists must be sanitized like custom rules."""
import json

from xrayui.core import render, routing
from xrayui.core.importer import parse_vless


def test_simple_bypass_ip_typo_is_dropped():
    rules = routing.build_rules(
        {"mode": "simple", "bypass_ips": ["999.999.999.999"], "bypass_domains": []})
    assert "999.999.999.999" not in json.dumps(rules)


def test_simple_bypass_domain_with_space_is_dropped():
    rules = routing.build_rules(
        {"mode": "simple", "bypass_ips": [], "bypass_domains": ["exa mple.com"]})
    assert "exa mple.com" not in json.dumps(rules)
    assert "domain:exa mple.com" not in json.dumps(rules)


def test_combined_repro_from_the_report():
    rules = routing.build_rules({"mode": "simple", "bypass_ips": ["999.999.999.999"],
                                 "bypass_domains": ["exa mple.com"]})
    blob = json.dumps(rules)
    assert "999.999.999.999" not in blob
    assert "exa mple.com" not in blob


def test_valid_simple_entries_are_unchanged():
    rules = routing.build_rules({"mode": "simple", "direct_private": False,
                                 "bypass_ips": ["10.0.0.0/8", "1.2.3.4", "geoip:ir"],
                                 "bypass_domains": ["example.com", "geosite:google"],
                                 "proxy_domains": ["netflix.com"]})
    blob = json.dumps(rules)
    for keep in ("10.0.0.0/8", "1.2.3.4", "geoip:ir",
                 "domain:example.com", "geosite:google", "domain:netflix.com"):
        assert keep in blob, keep


def test_typo_lines_still_render_a_valid_config():
    rules = routing.build_rules({"mode": "simple", "bypass_ips": ["999.999.999.999"],
                                 "bypass_domains": ["exa mple.com"]})
    text = render.build_text(
        parse_vless("vless://u@1.2.3.4:443?type=tcp&security=none#x"),
        "Wi-Fi", routing_rules=rules)
    json.loads(text)  # must stay valid JSON
    assert "999.999.999.999" not in text
    assert "exa mple.com" not in text
