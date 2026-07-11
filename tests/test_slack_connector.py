from open_notebook.domain.connectors.slack import SlackConnector


def test_authorize_url_uses_v2_and_scopes(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "cid")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "sec")
    url = SlackConnector().authorize_url("ST", "http://localhost:5055/api/connectors/slack/callback")
    assert "slack.com/oauth/v2/authorize" in url
    assert "pins:read" in url
    assert "state=ST" in url


def test_render_pins_concatenates_message_text():
    pins = [
        {"message": {"text": "first pinned", "user": "U1"}},
        {"message": {"text": "second pinned", "user": "U2"}},
    ]
    out = SlackConnector()._render_pins(pins)
    assert "first pinned" in out and "second pinned" in out
