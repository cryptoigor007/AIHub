from src.common.circuit import CircuitBreaker

def test_opens():
    cb = CircuitBreaker(failure_threshold=3, recovery_sec=60)
    assert not cb.is_open
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open
    cb.record_failure()
    assert cb.is_open
    cb.record_success()
    assert not cb.is_open

if __name__ == "__main__":
    test_opens()
    print("OK")
