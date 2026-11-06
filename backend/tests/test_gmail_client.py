import base64
import errno
from email import message_from_bytes
from pathlib import Path
from unittest.mock import Mock

import pytest

from gmail_client import _save_token, send_email


class FakeExecute:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeMessages:
    def __init__(self):
        self.sent = None

    def send(self, userId, body):
        self.sent = {"userId": userId, "body": body}
        return FakeExecute({"id": "message-123"})


class FakeUsers:
    def __init__(self):
        self.messages_api = FakeMessages()

    def messages(self):
        return self.messages_api


class FakeService:
    def __init__(self):
        self.users_api = FakeUsers()

    def users(self):
        return self.users_api


def test_send_email_uses_requested_recipient():
    service = FakeService()

    message_id = send_email(
        service, "Job matches", "Two new jobs", "recipient@example.com"
    )

    assert message_id == "message-123"
    sent = service.users_api.messages_api.sent
    assert sent["userId"] == "me"
    message = message_from_bytes(base64.urlsafe_b64decode(sent["body"]["raw"]))
    assert message["To"] == "recipient@example.com"
    assert message["Subject"] == "Job matches"


def test_save_token_allows_read_only_render_secret(
    tmp_path, monkeypatch, capsys
):
    credentials = Mock()
    credentials.to_json.return_value = '{"refresh_token":"token"}'
    monkeypatch.setattr(
        Path,
        "write_text",
        Mock(side_effect=OSError(errno.EROFS, "Read-only file system")),
    )

    _save_token(tmp_path / "token.json", credentials)

    assert "refreshed in memory" in capsys.readouterr().out


def test_save_token_does_not_hide_other_write_errors(monkeypatch):
    credentials = Mock()
    credentials.to_json.return_value = "{}"
    monkeypatch.setattr(
        Path,
        "write_text",
        Mock(side_effect=OSError(errno.ENOSPC, "No space left on device")),
    )

    with pytest.raises(OSError, match="No space left"):
        _save_token(Path("/tmp/token.json"), credentials)


def test_missing_client_secret_raises_not_configured(tmp_path, monkeypatch):
    from gmail_client import GmailNotConfiguredError, get_gmail_service

    monkeypatch.setenv("GMAIL_CREDENTIALS_PATH", str(tmp_path / "credentials.json"))
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "token.json"))

    with pytest.raises(GmailNotConfiguredError, match="client secret not found"):
        get_gmail_service()
    assert issubclass(GmailNotConfiguredError, FileNotFoundError)  # old handlers still work
