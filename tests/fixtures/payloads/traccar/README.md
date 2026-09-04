# Traccar payloads

Shapes taken from the Traccar OpenAPI document (`openapi.yaml` in the traccar/traccar
repository, schemas `Position`, `Device`, `Event`) and the API overview at
https://www.traccar.org/traccar-api/. Values are invented; they are not recordings from a
Traccar server. Replace them with recorded frames from the live run.

- `socket_frame.json`: one websocket frame with a position, a device and an event.
- `devices.json`: `GET /api/devices`.
