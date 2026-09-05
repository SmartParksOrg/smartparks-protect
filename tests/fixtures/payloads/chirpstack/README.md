# ChirpStack event fixtures

JSON examples from the ChirpStack v4 documentation, https://www.chirpstack.io/docs/chirpstack/integrations/events.html (fetched 2026-09-03), with a second gateway reception added to `up.json`. Recorded events from a real ChirpStack instance are added next to them as they come in, each with a note of its origin.

`up_opencollar_status_live.json`: the first recorded live event, an OpenCollar Edge status uplink (port 4) of collar SP051307 (DevEUI 0016C001F01192A0, firmware 7.2, hardware 1.8) received on 2026-09-05 10:56:43 UTC by chirpstack-dev4.smartparks.org through its HTTP integration, with ChirpStack's own decoder output in `object` for comparison. Uptime is days since boot in the firmware (the research document, section on port 4), which the driver reports in seconds.
