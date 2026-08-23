from dashboard.backend.security.redact import REDACTED, redact

SECRET_SHAPED_VALUES = [
    "sk-ant-api03-" + "a" * 48,
    "sk-" + "a" * 32,
    "Bearer abcdefghijklmnop.qrstuvwxyz123456",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "deadbeefdeadbeefdeadbeefdeadbeef",
]


def test_secret_keys_are_redacted_regardless_of_value():
    payload = {
        "COINBASE_API_KEY": "anything",
        "openai_api_key": "anything",
        "nested": {"DEEPSEEK_SECRET": "anything", "ok_field": "fine"},
        "a_token": "anything",
        "password": "anything",
    }
    out = redact(payload)
    assert out["COINBASE_API_KEY"] == REDACTED
    assert out["openai_api_key"] == REDACTED
    assert out["nested"]["DEEPSEEK_SECRET"] == REDACTED
    assert out["nested"]["ok_field"] == "fine"
    assert out["a_token"] == REDACTED
    assert out["password"] == REDACTED


def test_secret_shaped_values_are_scrubbed_even_under_innocuous_keys():
    for value in SECRET_SHAPED_VALUES:
        out = redact({"note": f"found this in a log line: {value}"})
        assert value not in out["note"], f"leaked: {value}"


def test_plain_values_pass_through_unchanged():
    payload = {"ticker": "BTC-USDC", "confidence": 87, "blockers": ["cooldown_active"]}
    assert redact(payload) == payload


def test_redacts_inside_lists_and_nested_structures():
    payload = {"orders": [{"client_order_id": "abc", "api_key": "shh"}]}
    out = redact(payload)
    assert out["orders"][0]["api_key"] == REDACTED
    assert out["orders"][0]["client_order_id"] == "abc"
