from mcp_security import redact_sensitive_data


def test_github_classic_token():
    assert "[REDACTED_GITHUB_TOKEN]" in redact_sensitive_data("token ghp_" + "A" * 36)


def test_github_fine_grained_token():
    assert "[REDACTED_GITHUB_TOKEN]" in redact_sensitive_data("github_pat_" + "A" * 30)


def test_slack_token():
    assert "[REDACTED_SLACK_TOKEN]" in redact_sensitive_data("xoxb-1234567890-abcdef")


def test_jwt():
    text = "eyJ" + "a" * 10 + ".eyJ" + "b" * 10 + "." + "c" * 12
    assert "[REDACTED_JWT]" in redact_sensitive_data(text)


def test_unaffected_text():
    assert redact_sensitive_data("hello world 12345") == "hello world 12345"
