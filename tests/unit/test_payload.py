import json

from app.adapters.payload import format_local_timestamp, to_payload


def test_to_payload_returns_json_string_of_named_fields():
    payload = to_payload(temperature=21.5, humidity=55.0)

    assert isinstance(payload, str)
    assert json.loads(payload) == {"temperature": 21.5, "humidity": 55.0}


def test_to_payload_with_no_fields_returns_empty_object():
    assert to_payload() == "{}"


def test_to_payload_matches_dht22_reading_unpacked_into_named_fields():
    temperature, humidity = (21.5, 55.0)

    payload = to_payload(temperature=temperature, humidity=humidity)

    assert json.loads(payload) == {"temperature": 21.5, "humidity": 55.0}


def test_to_payload_output_is_ready_for_publish_message(mocker):
    from app.services.publish import PublishService

    service = PublishService()
    service.client = mocker.Mock()

    service.publish_message(to_payload(state="on"))

    service.client.publish.assert_called_once_with(
        service.topics_pub[0], b'{"state": "on"}', qos=0, retain=False
    )


def test_format_local_timestamp_applies_positive_offset():
    epoch_seconds = 1786529613  # 2026-08-12T10:13:33Z

    assert format_local_timestamp(epoch_seconds, 480) == "2026-08-12T18:13:33+08:00"


def test_format_local_timestamp_applies_negative_offset():
    epoch_seconds = 1786529613  # 2026-08-12T10:13:33Z

    assert format_local_timestamp(epoch_seconds, -300) == "2026-08-12T05:13:33-05:00"


def test_format_local_timestamp_zero_offset_is_utc():
    epoch_seconds = 1786529613  # 2026-08-12T10:13:33Z

    assert format_local_timestamp(epoch_seconds, 0) == "2026-08-12T10:13:33+00:00"
