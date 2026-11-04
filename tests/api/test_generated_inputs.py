"""R12, replaying inputs proposed by the local language model (ai/datagen.py).

The expected result for each input comes from the written input rules, not
from the model. The model is not needed to run this test.
"""

import json
from pathlib import Path

import pytest

DATA = json.loads((Path(__file__).parents[1] / "data" / "generated_inputs.json").read_text(encoding="utf-8"))


@pytest.fixture
def fan(make_client, sign_in):
    # A generous rate limit, so a long run of generated seat IDs is judged on validation alone.
    client = make_client(hold_burst=10_000, hold_rate_per_second=10_000.0)
    return sign_in("lejie", client)


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: f"{c['field']}:{c['value']!r}"[:60])
def test_generated_input_is_judged_by_the_rules(fan, case):
    client, headers, value = fan.client, fan.headers, case["value"]
    if case["field"] == "seat_id":
        accepted = client.post("/api/hold/seats", json={"seat_id": value}, headers=headers).status_code != 422
    elif case["field"] == "card_number":
        accepted = client.post("/api/checkout", json={"card_number": value},
                               headers={**headers, "Idempotency-Key": "generated-case"}).status_code != 422
    elif case["field"] == "idempotency_key":
        accepted = client.post("/api/checkout", json={"card_number": "4000000000000002"},
                               headers={**headers, "Idempotency-Key": value}).status_code != 400
    else:
        accepted = client.post("/api/login", json={"username": value, "password": "x"}).status_code != 422
    assert accepted == case["expected_valid"]
