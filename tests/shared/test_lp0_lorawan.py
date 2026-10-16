"""The LoRaWAN 1.0 codec behind an offload station's files (phase 42, decision D321).

The golden is the firmware's own fixture: the "saved replay packet" of
`docs/reviews/lp0-wire-format.md` in `smartparks-opencollar-edge-fw` (protocol version 4,
2026-10-07), with its synthetic keys and address, which decrypts to the three-record stream the
document gives. The round trip builds frames the way the public replay app's `make_test_log.py`
builds them."""

import pytest

from shared.connectivity.adapters.lp0_station.lorawan import (
    Credentials,
    FrameError,
    Uplink,
    counter_candidates,
    decrypt_payload,
    parse_uplink,
    unwrap,
    verify_mic,
)

NWK_S_KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
APP_S_KEY = bytes.fromhex("101112131415161718191a1b1c1d1e1f")
DEV_ADDR = "26010203"
SAVED_REPLAY_PACKET = bytes.fromhex(
    "40030201260065001d9903be5dd95f109a3aab9e6baecc7e09a376a185164d2db542bae5d933560201d06b58b64e"
)
THREE_RECORDS = bytes.fromhex("120704040302017856341212070404030201785634121207040403020178563412")
CREDENTIALS = Credentials(DEV_ADDR, APP_S_KEY, NWK_S_KEY)


def test_firmware_fixture_parses_verifies_and_decrypts():
    uplink = parse_uplink(SAVED_REPLAY_PACKET)
    assert (uplink.dev_addr, uplink.f_cnt, uplink.f_port, uplink.confirmed) == (
        DEV_ADDR,
        101,
        29,
        False,
    )
    assert verify_mic(uplink, NWK_S_KEY)
    assert decrypt_payload(uplink, APP_S_KEY, NWK_S_KEY) == THREE_RECORDS
    unwrapped = unwrap(SAVED_REPLAY_PACKET, CREDENTIALS)
    assert (unwrapped.payload, unwrapped.f_port, unwrapped.f_cnt) == (THREE_RECORDS, 29, 101)


def test_wrong_key_or_changed_byte_fails_the_mic():
    uplink = parse_uplink(SAVED_REPLAY_PACKET)
    assert not verify_mic(uplink, APP_S_KEY)
    tampered = bytearray(SAVED_REPLAY_PACKET)
    tampered[20] ^= 0x01
    assert not verify_mic(parse_uplink(bytes(tampered)), NWK_S_KEY)
    with pytest.raises(FrameError, match="does not verify"):
        unwrap(bytes(tampered), CREDENTIALS)


def test_another_devices_address_is_refused_before_the_keys_are_tried():
    with pytest.raises(FrameError, match="addressed to 26010203"):
        unwrap(SAVED_REPLAY_PACKET, Credentials("26010204", APP_S_KEY, NWK_S_KEY))


def test_not_an_uplink():
    with pytest.raises(FrameError, match="shorter"):
        parse_uplink(b"\x40\x01\x02")
    with pytest.raises(FrameError, match="MHDR"):
        parse_uplink(b"\x60" + SAVED_REPLAY_PACKET[1:])


def build_uplink(
    credentials: Credentials, f_cnt: int, f_port: int, payload: bytes, *, f_opts: bytes = b""
) -> bytes:
    """A LoRaWAN 1.0 uplink the way `make_test_log.py` builds one, for the round trip."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.cmac import CMAC

    dev_addr_le = bytes.fromhex(credentials.dev_addr)[::-1]
    fhdr = dev_addr_le + bytes([len(f_opts) & 0x0F, f_cnt & 0xFF, (f_cnt >> 8) & 0xFF]) + f_opts
    key = credentials.nwk_s_key if f_port == 0 else credentials.app_s_key
    cipher = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    encrypted = bytearray()
    for index in range(0, len(payload), 16):
        block = (
            bytes([0x01, 0, 0, 0, 0, 0])
            + dev_addr_le
            + (f_cnt & 0xFFFFFFFF).to_bytes(4, "little")
            + bytes([0, index // 16 + 1])
        )
        stream = cipher.update(block)
        chunk = payload[index : index + 16]
        encrypted += bytes(a ^ b for a, b in zip(chunk, stream, strict=False))
    mac_payload = fhdr + bytes([f_port]) + bytes(encrypted)
    signed = b"\x40" + mac_payload
    b0 = (
        bytes([0x49, 0, 0, 0, 0, 0])
        + dev_addr_le
        + (f_cnt & 0xFFFFFFFF).to_bytes(4, "little")
        + bytes([0, len(signed)])
    )
    cmac = CMAC(algorithms.AES(credentials.nwk_s_key))
    cmac.update(b0 + signed)
    return signed + cmac.finalize()[:4]


def test_round_trip_matches_the_fixture_and_skips_fopts():
    assert build_uplink(CREDENTIALS, 101, 29, THREE_RECORDS) == SAVED_REPLAY_PACKET
    with_opts = build_uplink(CREDENTIALS, 7, 4, b"\xf4\x01\x02", f_opts=b"\x02\x30")
    uplink = parse_uplink(with_opts)
    assert uplink.f_opts == b"\x02\x30" and uplink.f_port == 4
    assert (unwrap(with_opts, CREDENTIALS).payload, unwrap(with_opts, CREDENTIALS).f_port) == (
        b"\xf4\x01\x02",
        4,
    )


def test_port_zero_takes_the_network_key_and_an_empty_payload_stays_empty():
    mac_only = build_uplink(CREDENTIALS, 9, 0, b"\x02")
    assert (unwrap(mac_only, CREDENTIALS).payload, unwrap(mac_only, CREDENTIALS).f_port) == (
        b"\x02",
        0,
    )
    empty = parse_uplink(build_uplink(CREDENTIALS, 10, 29, b""))
    assert empty.frm_payload == b"" and empty.f_port == 29
    assert decrypt_payload(empty, APP_S_KEY, NWK_S_KEY) == b""


def test_counter_upper_half_is_never_assumed():
    uplink = parse_uplink(SAVED_REPLAY_PACKET)
    assert not verify_mic(uplink, NWK_S_KEY, f_cnt=0x10000 + 101)


def test_a_rolled_over_counter_is_read_from_the_last_verified_one():
    """Firmware issue 772 asks for correct frame counter semantics; a frame carries 16 bits
    and a receiver reconstructs the rest from where the device was (LoRaWAN 1.0 rollover).
    Without a last counter only the upper half zero is tried, with one the device's half and
    the next; the MIC decides and nothing else is guessed."""
    rolled = build_uplink(CREDENTIALS, 0x10005, 29, THREE_RECORDS)
    assert parse_uplink(rolled).f_cnt == 5
    with pytest.raises(FrameError, match="does not verify"):
        unwrap(rolled, CREDENTIALS)
    assert unwrap(rolled, CREDENTIALS, last_f_cnt=0x0FFFF).f_cnt == 0x10005
    assert unwrap(rolled, CREDENTIALS, last_f_cnt=0x10002).f_cnt == 0x10005
    assert counter_candidates(5, 0x2_0000) == [5, 0x20005, 0x30005]
    assert counter_candidates(5, None) == [5]
    assert counter_candidates(5, 0xFFFF_0000) == [5, 0xFFFF0005]
    plain = build_uplink(CREDENTIALS, 7, 29, THREE_RECORDS)
    assert unwrap(plain, CREDENTIALS, last_f_cnt=0x10002).f_cnt == 7  # zero is tried first


def test_an_unknown_metadata_version_is_refused_by_name():
    """LP0 v5 writes `lp0.version`; a version Protect has not read the contract of is refused
    by name (decision D327), a missing one is an older station firmware's file."""
    from shared.connectivity.adapters.lp0_station import METADATA_VERSIONS, Lp0StationAdapter

    assert {5} == METADATA_VERSIONS
    assert Lp0StationAdapter.unwrap_frame(SAVED_REPLAY_PACKET, CREDENTIALS).f_cnt == 101
    assert Lp0StationAdapter.unwrap_frame(SAVED_REPLAY_PACKET, CREDENTIALS, lp0_version=5)
    with pytest.raises(FrameError, match="version 6 is not one this version reads"):
        Lp0StationAdapter.unwrap_frame(SAVED_REPLAY_PACKET, CREDENTIALS, lp0_version=6)
    with pytest.raises(FrameError, match="version 4 is not one"):
        Lp0StationAdapter.unwrap_frame(SAVED_REPLAY_PACKET, CREDENTIALS, lp0_version=4)


def test_the_firmware_signs_with_the_sixteen_bit_counter_and_wraps():
    """LP0 v5: `lorawan_tools_build` takes the wrapping 16-bit allocator's value as a 32-bit
    counter with the upper half zero, so the frame carries the whole counter it was signed
    with. 65535 verifies, the next frame at 0 verifies after it (the upper half zero is tried
    first, whatever the device was last seen at), and the wrap reuses the keystream, which
    is the firmware's limit: the same records at counter 0 encrypt to the same bytes."""
    high = build_uplink(CREDENTIALS, 0xFFFF, 29, THREE_RECORDS)
    assert parse_uplink(high).f_cnt == 0xFFFF
    assert unwrap(high, CREDENTIALS).f_cnt == 0xFFFF
    low = build_uplink(CREDENTIALS, 0, 29, THREE_RECORDS)
    after_wrap = unwrap(low, CREDENTIALS, last_f_cnt=0xFFFF)
    assert (after_wrap.f_cnt, after_wrap.payload) == (0, THREE_RECORDS)
    assert counter_candidates(0, 0xFFFF)[0] == 0
    assert build_uplink(CREDENTIALS, 0, 29, THREE_RECORDS) == low  # the reuse, recorded
    # the frames the firmware builds are unconfirmed, port 29
    assert high[0] == 0x40 and parse_uplink(high).f_port == 29


def test_credentials_validate_their_shape():
    with pytest.raises(ValueError):
        Credentials(DEV_ADDR, b"\x00" * 15, NWK_S_KEY)
    with pytest.raises(ValueError):
        Credentials("2601020", APP_S_KEY, NWK_S_KEY)
    assert isinstance(parse_uplink(SAVED_REPLAY_PACKET), Uplink)
