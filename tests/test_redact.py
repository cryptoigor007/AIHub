from src.common.redact import redact_secrets

def test_token():
    s = redact_secrets("token=abcdefghijklmnopqrstuvwxyz1234")
    assert "***" in s
    assert "abcd" not in s or "token=***" in s

def test_bearer():
    s = redact_secrets("Authorization Bearer abcdefghijklmnopqr_st")
    assert "***" in s

if __name__ == "__main__":
    test_token()
    test_bearer()
    print("OK")
