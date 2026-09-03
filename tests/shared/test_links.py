import uuid

from shared.domain.links import render, resolve_links
from shared.models import DataSource, ExternalIdentity


def test_render_leaves_out_incomplete_templates():
    assert (
        render("{web_url}/d/{external_id}", {"web_url": "http://x", "external_id": "A"})
        == "http://x/d/A"
    )
    assert render("{web_url}/d/{external_id}", {"web_url": "http://x"}) is None


def test_chirpstack_links_from_identity_attributes():
    source = DataSource(
        id=uuid.uuid4(),
        name="CS",
        adapter_key="chirpstack",
        config={"web_url": "http://localhost:8080"},
        link_templates={},
    )
    identity = ExternalIdentity(
        data_source_id=source.id,
        external_id="70B3D57ED0001234",
        attributes={"tenant_id": "t1", "application_id": "a1"},
    )
    links = {link["key"]: link for link in resolve_links(source, identity)}
    assert (
        links["OPEN_DEVICE"]["url"]
        == "http://localhost:8080/#/tenants/t1/applications/a1/devices/70B3D57ED0001234"
    )
    assert links["OPEN_APPLICATION"]["url"].endswith("/applications/a1")
    assert links["OPEN_DEVICE"]["label"] == "Open device in ChirpStack"
    assert "OPEN_GATEWAY" not in links
    with_gateway = {link["key"] for link in resolve_links(source, identity, gateway_id="gw1")}
    assert "OPEN_GATEWAY" in with_gateway


def test_admin_override_wins_and_generic_has_no_links():
    source = DataSource(
        id=uuid.uuid4(),
        name="CS",
        adapter_key="chirpstack",
        config={"web_url": "http://x"},
        link_templates={"OPEN_DEVICE": "https://custom/{external_id}"},
    )
    identity = ExternalIdentity(data_source_id=source.id, external_id="E", attributes={})
    links = {link["key"]: link["url"] for link in resolve_links(source, identity)}
    assert links["OPEN_DEVICE"] == "https://custom/E"
    generic = DataSource(
        id=uuid.uuid4(), name="G", adapter_key="generic_http", config={}, link_templates={}
    )
    assert resolve_links(generic, identity) == []
