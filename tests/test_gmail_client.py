import base64
from email import message_from_bytes

from gmail_client import send_email


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
