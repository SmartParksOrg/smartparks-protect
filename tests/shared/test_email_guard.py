"""The mail guard: development delivers to DEV_NOTIFY_EMAILS only, unless MAIL_DELIVER_TO_ALL
lifts it (2026-09-13); production delivers to everyone; nothing without SMTP settings."""

from types import SimpleNamespace

from shared.notifications import email


def _settings(**overrides):
    base = {
        "mail_configured": True,
        "environment": "development",
        "dev_notify_email_list": {"tim@example.org"},
        "mail_deliver_to_all": False,
    }
    return SimpleNamespace(**{**base, **overrides})


def test_guard(monkeypatch):
    monkeypatch.setattr(email, "get_settings", lambda: _settings())
    assert email.allowed_recipient("Tim@example.org") == (True, "")
    allowed, reason = email.allowed_recipient("ranger@example.org")
    assert not allowed and "MAIL_DELIVER_TO_ALL" in reason
    monkeypatch.setattr(email, "get_settings", lambda: _settings(mail_deliver_to_all=True))
    assert email.allowed_recipient("ranger@example.org") == (True, "")
    monkeypatch.setattr(email, "get_settings", lambda: _settings(environment="production"))
    assert email.allowed_recipient("anyone@example.org") == (True, "")
    monkeypatch.setattr(email, "get_settings", lambda: _settings(mail_configured=False))
    assert email.allowed_recipient("tim@example.org") == (False, "mail is not configured")
