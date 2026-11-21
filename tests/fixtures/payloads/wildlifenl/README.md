# WildlifeNL fixtures

- `openapi_test_detection.json` and `openapi_live_detection.json`: the part of the two servers'
  own OpenAPI documents that describes `POST /detection/`, cut from
  `https://test-api-wildlifenl.uu.nl/openapi.json` (version 20261116) and
  `https://live-api-wildlifenl.uu.nl/openapi.json` (version 20260826), both read on 2026-11-21
  without an account. Only `info`, the request body of the path and the `DetectionRecord` schema
  are kept; nothing is changed. The TEST server takes `speciesName`, the LIVE server `speciesID`,
  and both refuse a field the schema does not name (`additionalProperties: false`).
- `active_deployments.json`: an answer of `GET /borne-sensor-deployment/active/` written by hand
  from the `BorneSensorDeployment` schema of the TEST document and the source
  (`stores/BorneSensorDeploymentStore.go` at the push of 2026-11-16). It is not a recorded
  answer: no account existed when it was made. Replace it with a recorded one after the first
  live test.
