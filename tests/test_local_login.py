from src.common.authpolicy import local_login_allowed


def test_off():
    assert not local_login_allowed("off", "127.0.0.1")


def test_loopback_allows_only_local():
    assert local_login_allowed("loopback", "127.0.0.1")
    assert local_login_allowed("loopback", "::1")
    assert not local_login_allowed("loopback", "192.168.1.50")
    assert not local_login_allowed("loopback", "8.8.8.8")


def test_lan_allows_any():
    assert local_login_allowed("lan", "192.168.1.50")


def test_default_is_loopback():
    assert local_login_allowed("", "127.0.0.1")
    assert not local_login_allowed("", "192.168.1.50")
