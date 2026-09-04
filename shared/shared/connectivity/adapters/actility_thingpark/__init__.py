"""Actility ThingPark, public or private (architecture 7.2, decision D84).

The same ThingPark application server events and downlink API as KPN LoRa, which runs on
ThingPark: this adapter reuses that code with its own key, label, defaults and setup text.
ThingPark Enterprise and ThingPark Wireless deployments differ in what a subscription may do
(architecture 8.2); base station management is not attempted here.
"""

from typing import Any, ClassVar

from shared.connectivity.adapters.kpn_thingpark import KpnThingParkAdapter


class ActilityThingParkAdapter(KpnThingParkAdapter):
    key: ClassVar[str] = "actility_thingpark"
    label: ClassVar[str] = "Actility ThingPark"
    config_example: ClassVar[dict[str, Any]] = {
        "downlink_url": "https://community.thingpark.io/thingpark/lrc/rest/downlink",
        "auth_mode": "token",
        "as_id": "TWA_100000000.1",
        "web_url": "https://community.thingpark.io/wlogger",
    }
    setup_hint: ClassVar[str] = (
        "In ThingPark create an application server of type HTTP pointing at the webhook URL of "
        "this data source with the bearer token as Authorization header (`Authorization: "
        "Bearer <token>` in the custom headers), and route the devices' routing profile to "
        "it. Downlinks use the LRC downlink API with the AS key (token mode) or a bearer."
    )
