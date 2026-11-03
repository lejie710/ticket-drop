# AI-generated input data

Model: ollama:llama3.2, 4 calls, 117 s of model time. Run at 2026-11-03 15:17 UTC.

| Field | Proposed | Unique | Novel vs hand-written | Model label correct | Sendable | App agrees with oracle |
|---|---|---|---|---|---|---|
| seat_id | 15 | 14 | 14 | 13/14 | 14 | 14/14 |
| card_number | 15 | 11 | 11 | 7/11 | 11 | 11/11 |
| idempotency_key | 14 | 13 | 13 | 13/13 | 13 | 13/13 |
| username | 15 | 14 | 14 | 11/14 | 14 | 14/14 |

## Where the app and the written rules disagree

None. Every sendable generated input was accepted or rejected exactly as the rules say.

## Examples where the model labelled its own input wrongly

- seat_id `'—-09'`: model said valid (); rules say invalid
- card_number `'12345678901234567890 '`: model said invalid (Whitespace not allowed); rules say valid
- card_number `'123456789012345678901'`: model said invalid (Value too long); rules say valid
- card_number `' 12345678901234567890 '`: model said invalid (Whitespace not allowed); rules say valid
- card_number `'123456789012345678901234567890'`: model said valid (Valid card number); rules say invalid
- username `'\ufffatest_username￼'`: model said valid (); rules say invalid
- username `'test'`: model said invalid (Input is too short); rules say valid
- username `'�test_username�'`: model said valid (); rules say invalid

The model label is measured but never used as an expected result. Accuracy here describes this small local model on this run, not language models in general.
