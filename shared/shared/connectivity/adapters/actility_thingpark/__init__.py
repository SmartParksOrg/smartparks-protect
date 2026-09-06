"""Actility ThingPark, public or private (architecture 7.2, decision D84).

The same ThingPark application server events and downlink API as KPN LoRa, which runs on
ThingPark: this adapter reuses that code with its own key, label, defaults and setup text.
ThingPark Enterprise and ThingPark Wireless deployments differ in what a subscription may do
(architecture 8.2); base station management is not attempted here.
"""

from typing import Any, ClassVar

from shared.connectivity.adapters.kpn_thingpark import (
    KpnThingParkAdapter,
    thingpark_channels,
    thingpark_config_schema,
)


class ActilityThingParkAdapter(KpnThingParkAdapter):
    key: ClassVar[str] = "actility_thingpark"
    label: ClassVar[str] = "Actility ThingPark"
    # Every deployment has its own LRC, so the downlink endpoint is asked for.
    channels: ClassVar[list[dict[str, Any]]] = thingpark_channels(downlink_url_required=True)
    config_schema: ClassVar[dict[str, Any]] = thingpark_config_schema(None)
    default_downlink_url: ClassVar[str | None] = None
    config_example: ClassVar[dict[str, Any]] = {
        "downlink_url": "https://community.thingpark.io/thingpark/lrc/rest/downlink",
        "web_url": "https://community.thingpark.io/wlogger",
    }
    setup_hint: ClassVar[str] = (
        "In ThingPark create an application server (or connection) of type HTTP pointing at the "
        "webhook URL of this data source, and route the devices to it. Store the tunnel "
        "interface authentication key as as_key: ThingPark's own Token then authenticates "
        "every push; a custom header `Authorization: Bearer <webhook token>` works as well. "
        "Downlinks go to the deployment's LRC downlink endpoint, signed with the same key."
    )
