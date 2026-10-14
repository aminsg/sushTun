"""T2-DNS1 + T2-DNS2: resolver validation and dict-server cleaning."""
from xrayui.core import dns as dns_mod


def test_out_of_range_quads_are_rejected():
    for bad in ("999.999.999.999", "1.2.3.999", "300.300.300.300", "256.1.1.1"):
        assert dns_mod.validate_server(bad), bad
        assert dns_mod.clean_servers([bad]) == [], bad


def test_all_numeric_tld_is_rejected():
    assert dns_mod.validate_server("example.123")
    assert dns_mod.validate_server("123")


def test_valid_ipv4_ipv6_hostnames_and_doh_still_accepted():
    for good in ("8.8.8.8", "1.1.1.1", "dns.google", "example.com",
                 "2606:4700:4700::1111", "udp://8.8.8.8:5353",
                 "https://1.1.1.1/dns-query", "tcp://8.8.8.8"):
        assert dns_mod.validate_server(good) == "", good


def test_bare_host_port_still_suggests_a_scheme():
    assert "scheme" in dns_mod.validate_server("8.8.8.8:5353")


def test_clean_servers_drops_dicts_without_a_usable_address():
    assert dns_mod.clean_servers([{}]) == []
    assert dns_mod.clean_servers([{"port": 53}]) == []
    assert dns_mod.clean_servers([{"address": "999.999.999.999"}]) == []
    assert dns_mod.clean_servers([{"address": "not a server"}]) == []


def test_clean_servers_keeps_valid_dict_servers():
    valid = {"address": "8.8.8.8", "port": 53}
    full = {"address": "1.1.1.1", "domains": ["domain:ir"],
            "expectIPs": ["1.1.1.1"], "skipFallback": True}
    assert dns_mod.clean_servers([valid]) == [valid]
    assert dns_mod.clean_servers([full]) == [full]
    assert dns_mod.clean_servers(["1.1.1.1", full]) == ["1.1.1.1", full]
