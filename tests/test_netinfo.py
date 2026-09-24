
from src.common.netinfo import is_loopback_ip, is_private_ip, network_hint_message, lan_http_urls

def test_private():
    assert is_private_ip("192.168.1.10")
    assert is_private_ip("10.0.0.1")
    assert is_private_ip("127.0.0.1")
    assert not is_private_ip("8.8.8.8")

def test_loopback():
    assert is_loopback_ip("127.0.0.1")
    assert is_loopback_ip("::1")
    assert not is_loopback_ip("192.168.1.10")
    assert not is_loopback_ip("8.8.8.8")
    assert not is_loopback_ip("not-an-ip")

def test_hint():
    t = network_hint_message(has_mesh_url=True, lan_urls=["http://192.168.0.2:8787/p/x/"])
    assert "Tailscale" in t
    assert "192.168" in t

def test_hint_without_mesh():
    t = network_hint_message(has_mesh_url=False, lan_urls=[])
    assert "Tailscale" in t
    assert "enable_tailscale_serve" in t

def test_lan_urls_type():
    u = lan_http_urls(8787, "/p/abc")
    assert isinstance(u, list)

if __name__ == "__main__":
    test_private()
    test_loopback()
    test_hint()
    test_hint_without_mesh()
    test_lan_urls_type()
    print("OK")
