from ML.explain_daily import _extract_json_object


def test_extract_json_object_accepts_valid_payload():
    payload = _extract_json_object(
        '{"reason_summary": "Скорее снижение.", "reason_1": "Трафик слабый.", "reason_2": "Реклама не конвертирует.", "reason_3": "Краткосрочный спрос ниже базы."}'
    )
    assert payload["reason_summary"] == "Скорее снижение."
    assert payload["reason_1"] == "Трафик слабый."


def test_extract_json_object_rejects_missing_keys():
    try:
        _extract_json_object('{"reason_summary": "ok"}')
    except ValueError:
        return
    raise AssertionError("Expected ValueError for missing explanation keys")
