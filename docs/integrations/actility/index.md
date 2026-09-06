# Actility ThingPark

Actility ThingPark Wireless and ThingPark Enterprise, public or private, as a LoRaWAN source
(decision D84). The adapter is the [KPN LoRa adapter](../kpn-thingpark/index.md) under its own
name: KPN runs on ThingPark, so the application server events, the gateway receptions
(`Lrrs`) and the LRC downlink API are identical. Only the defaults and the setup text differ.

## Setup

1. Under Server admin, Data sources: New data source, adapter Actility ThingPark. Config:
   `downlink_url` (the LRC downlink endpoint of the deployment, for example
   `https://community.thingpark.io/thingpark/lrc/rest/downlink`), `auth_mode` (`token` with
   `as_id` and the `as_key` credential, or `bearer` with `api_token`), `web_url` for deep links.
2. In ThingPark create an application server (ThingPark Wireless) or an HTTP connection
   (ThingPark Enterprise) pointing at the webhook URL of the data source, and route the
   devices to it. Activate its security and enter the AS ID and a tunnel interface
   authentication key; store the key as the `as_key` credential and ThingPark's own Token in
   the URL authenticates every push. ThingPark Enterprise also allows custom headers, so
   `Authorization: Bearer <token>` works as the alternative.
3. The DevEUI is the device identity.

Capabilities depend on the deployment and the subscription (architecture 8.2): base station
management is not attempted through this adapter. Everything else, including troubleshooting,
is as documented for KPN.
