# Example payloads

Payloads accepted by the generic sources. Recorded real payloads of production platforms live in `tests/fixtures/payloads/<provider>/` with a README naming their origin.

## Generic HTTP with the generic JSON driver

```bash
curl -X POST http://localhost:8000/api/v1/ingest/http/<data_source_id> \
  -H "Authorization: Bearer <webhook token>" -H "Content-Type: application/json" \
  -d @generic_http_uplink.json
```
