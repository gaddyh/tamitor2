"""Tests for the 360dialog event adapter (webhook → BotEvent)."""

from __future__ import annotations

import pytest

from echo_v2.integrations.dialog360.events import Dialog360EventAdapter
from echo_v2.ports.bot import BotEventAdapter, BotEventType


def test_adapter_satisfies_port():
    assert isinstance(Dialog360EventAdapter(), BotEventAdapter)


def test_parse_text_message():
    adapter = Dialog360EventAdapter()
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.HBHKGUY",
                        "from": "972500000001",
                        "type": "text",
                        "text": {"body": "מחר ב-8"},
                        "timestamp": "1700000000",
                    }],
                    "contacts": [
                        {"profile": {"name": "Gaddy"}, "wa_id": "972500000001"}
                    ],
                    "metadata": {"phone_number_id": "business-123"},
                }
            }]
        }]
    }
    event = adapter.parse(payload)
    assert event is not None
    assert event.event_id == "wamid.HBHKGUY"
    assert event.user_phone == "972500000001"
    assert event.business_phone_number_id == "business-123"
    assert event.type is BotEventType.TEXT
    assert event.text == "מחר ב-8"
    assert event.timestamp is not None


def test_parse_contact_message():
    adapter = Dialog360EventAdapter()
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.CONTACT1",
                        "from": "972500000001",
                        "type": "contacts",
                        "contacts": [{
                            "name": {
                                "formatted_name": "Dana Cohen",
                                "first_name": "Dana",
                                "last_name": "Cohen",
                            },
                            "phones": [
                                {"wa_id": "972526610653", "phone": "+972 52-661-0653"}
                            ],
                        }],
                        "timestamp": "1700000001",
                    }],
                    "contacts": [
                        {"profile": {"name": "Gaddy"}, "wa_id": "972500000001"}
                    ],
                }
            }]
        }]
    }
    event = adapter.parse(payload)
    assert event is not None
    assert event.type is BotEventType.CONTACT
    assert event.contact is not None
    assert event.contact.phone == "972526610653"
    assert event.contact.name == "Dana Cohen"


def test_parse_contact_prefers_wa_id_over_phone():
    adapter = Dialog360EventAdapter()
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.C2",
                        "from": "972500000001",
                        "type": "contacts",
                        "contacts": [{
                            "name": {"formatted_name": "Bob"},
                            "phones": [
                                {"phone": "+1 555-1234"},
                                {"wa_id": "15551234567"},
                            ],
                        }],
                    }],
                    "contacts": [{"wa_id": "972500000001"}],
                }
            }]
        }]
    }
    event = adapter.parse(payload)
    assert event is not None
    assert event.contact.phone == "15551234567"


def test_parse_contact_no_phones_returns_none():
    adapter = Dialog360EventAdapter()
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.C3",
                        "from": "972500000001",
                        "type": "contacts",
                        "contacts": [{
                            "name": {"formatted_name": "Empty"},
                            "phones": [],
                        }],
                    }],
                    "contacts": [{"wa_id": "972500000001"}],
                }
            }]
        }]
    }
    assert adapter.parse(payload) is None


def test_parse_status_update_returns_none():
    """Status updates (delivery receipts) are not user messages."""
    adapter = Dialog360EventAdapter()
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "statuses": [{
                        "id": "wamid.S1",
                        "status": "delivered",
                    }],
                }
            }]
        }]
    }
    assert adapter.parse(payload) is None


def test_parse_empty_payload_returns_none():
    adapter = Dialog360EventAdapter()
    assert adapter.parse({}) is None
    assert adapter.parse(None) is None  # type: ignore[arg-type]


def test_parse_unknown_message_type_returns_none():
    adapter = Dialog360EventAdapter()
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.X",
                        "from": "972500000001",
                        "type": "sticker",
                    }],
                    "contacts": [{"wa_id": "972500000001"}],
                }
            }]
        }]
    }
    assert adapter.parse(payload) is None


def test_parse_missing_message_id_returns_none():
    adapter = Dialog360EventAdapter()
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "972500000001",
                        "type": "text",
                        "text": {"body": "hi"},
                    }],
                    "contacts": [{"wa_id": "972500000001"}],
                }
            }]
        }]
    }
    assert adapter.parse(payload) is None


def test_parse_falls_back_to_message_from_for_phone():
    """If contacts[] is missing, use message.from as the sender phone."""
    adapter = Dialog360EventAdapter()
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": "wamid.F1",
                        "from": "972500000099",
                        "type": "text",
                        "text": {"body": "hello"},
                    }],
                }
            }]
        }]
    }
    event = adapter.parse(payload)
    assert event is not None
    assert event.user_phone == "972500000099"


def _payload(message: dict, *, contacts: list | None = None, metadata: dict | None = None) -> dict:
    value = {"messages": [message], "contacts": contacts or []}
    if metadata is not None:
        value["metadata"] = metadata
    return {"entry": [{"changes": [{"value": value}]}]}


@pytest.mark.parametrize("message", [None, "bad", 123])
def test_parse_non_object_message_returns_none(message):
    payload = _payload({"id": "unused"})
    payload["entry"][0]["changes"][0]["value"]["messages"] = [message]
    assert Dialog360EventAdapter().parse(payload) is None


def test_parse_missing_sender_returns_none():
    assert Dialog360EventAdapter().parse(_payload({"id": "m1", "type": "text", "text": {"body": "hello"}})) is None


@pytest.mark.parametrize("body", [{}, {"body": ""}, "not a dict"])
def test_parse_empty_text_returns_none(body):
    message = {"id": "m1", "from": "972500000001", "type": "text", "text": body}
    assert Dialog360EventAdapter().parse(_payload(message)) is None


@pytest.mark.parametrize("contacts", [[], ["invalid"]])
def test_parse_empty_shared_contact_returns_none(contacts):
    message = {"id": "m1", "from": "972500000001", "type": "contacts", "contacts": contacts}
    assert Dialog360EventAdapter().parse(_payload(message)) is None


def test_parse_contact_uses_phone_when_wa_id_missing():
    message = {
        "id": "m1", "from": "972500000001", "type": "contacts",
        "contacts": [{"name": "unexpected", "phones": [None, {"phone": "+972 50-000-0002"}]}],
    }
    event = Dialog360EventAdapter().parse(_payload(message, metadata={"phone_number_id": "business-456"}))
    assert event is not None
    assert event.contact.name == ""
    assert event.contact.phone == "+972 50-000-0002"
    assert event.business_phone_number_id == "business-456"


def test_parse_contact_uses_first_and_last_names():
    message = {
        "id": "m1", "from": "972500000001", "type": "contacts",
        "contacts": [{"name": {"first_name": "Dana", "last_name": "Cohen"}, "phones": [{"wa_id": "972500000002"}]}],
    }
    event = Dialog360EventAdapter().parse(_payload(message))
    assert event is not None
    assert event.contact.name == "Dana Cohen"


@pytest.mark.parametrize("payload", [
    {"entry": [{"changes": []}]},
    {"entry": [{"changes": [{"value": []}]}]},
])
def test_parse_invalid_change_returns_none(payload):
    assert Dialog360EventAdapter().parse(payload) is None


def test_parse_invalid_timestamp_is_ignored():
    message = {"id": "m1", "from": "972500000001", "type": "text", "text": {"body": "hello"}, "timestamp": "invalid"}
    event = Dialog360EventAdapter().parse(_payload(message))
    assert event is not None
    assert event.timestamp is None
