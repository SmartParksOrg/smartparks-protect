"""External deep links (architecture 21.3): a data source's link templates plus the identity's
attributes give "Open in <platform>" URLs without provider code in the domain or the UI.

Templates use `{placeholder}` fields. Available placeholders: every key of the data source
config (for example `web_url`), every key of the external identity attributes (`tenant_id`,
`application_id`), `external_id`, and for gateways `gateway_id`. A template whose placeholders
cannot all be filled is left out rather than rendered broken.
"""

import string
from typing import Any

from shared.connectivity.registry import ADAPTERS
from shared.models import DataSource, ExternalIdentity

LINK_LABELS = {
    "OPEN_DEVICE": "Open device in {platform}",
    "OPEN_APPLICATION": "Open application in {platform}",
    "OPEN_GATEWAY": "Open gateway in {platform}",
    "OPEN_EVENT": "Open event in {platform}",
}


def templates_for(source: DataSource) -> dict[str, str]:
    adapter = ADAPTERS.get(source.adapter_key)
    defaults = dict(adapter.default_link_templates) if adapter else {}
    return {**defaults, **{k: str(v) for k, v in (source.link_templates or {}).items() if v}}


def render(template: str, values: dict[str, Any]) -> str | None:
    fields = [f for _, f, _, _ in string.Formatter().parse(template) if f]
    if any(values.get(f) in (None, "") for f in fields):
        return None
    return template.format(**{f: values[f] for f in fields})


def resolve_links(
    source: DataSource, identity: ExternalIdentity | None = None, *, gateway_id: str | None = None
) -> list[dict[str, str]]:
    adapter = ADAPTERS.get(source.adapter_key)
    platform = adapter.label if adapter else source.adapter_key
    values: dict[str, Any] = {**(source.config or {})}
    if identity is not None:
        values.update(identity.attributes or {})
        values["external_id"] = identity.external_id
        # Platforms differ in the case of a DevEUI in their URLs; ChirpStack shows lower case.
        values["external_id_lower"] = identity.external_id.lower()
        values["external_id_upper"] = identity.external_id.upper()
    if gateway_id is not None:
        values["gateway_id"] = gateway_id
    links = []
    for key, template in templates_for(source).items():
        if key == "OPEN_GATEWAY" and gateway_id is None:
            continue
        if key in ("OPEN_DEVICE",) and identity is None:
            continue
        url = render(template, values)
        if url is not None:
            links.append(
                {
                    "key": key,
                    "label": LINK_LABELS.get(key, key.replace("_", " ").capitalize()).format(
                        platform=platform
                    ),
                    "url": url,
                    "data_source_id": str(source.id),
                    "data_source_name": source.name,
                }
            )
    return links
