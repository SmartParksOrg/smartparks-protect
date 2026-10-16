"""The LoRaWAN 1.0 uplink an offload station writes to its card (phase 42, decision D321).

A station stores each offloaded frame as an ordinary LoRaWAN 1.0 uplink under the tracker's own
keys (LP0 v5, firmware issue 772: the collar builds the frame with `lorawan_tools_build` under
its own `lp0_dev_addr`, `lp0_app_key` and `lp0_network_key`, the station authenticates the
transport with the deployment master key and stores the frame unchanged): MHDR `0x40`, the
DevAddr, FCtrl, a 16-bit frame counter, port 29, the FRMPayload encrypted with the AppSKey (the
NwkSKey on port 0) and a MIC under the NwkSKey. The counter is the firmware's wrapping 16-bit
allocator passed as a 32-bit value with the upper half zero, so the frame carries the whole
counter the MIC was computed with; `unwrap` tries that first and, as a LoRaWAN receiver would,
the upper half the device was last verified at. The 16-bit wrap under unchanged keys reuses the
keystream after 65536 frames; that is the firmware's limit, recorded here, never worked around.

Pure: bytes and keys in, bytes out. The arithmetic is the LoRaWAN 1.0.x specification's (the
A and B0 blocks), as the public replay app's `make_test_log.py` builds them; the golden test is
the firmware's own fixture in `docs/reviews/lp0-wire-format.md`, which verifies and decrypts
here to the three records the document names.
"""

from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.cmac import CMAC

MHDR_UNCONFIRMED_UP = 0x40
MHDR_CONFIRMED_UP = 0x80
UPLINK = 0
MIC_BYTES = 4
#: DevAddr, FCtrl and the 16-bit counter.
FHDR_FIXED_BYTES = 7


class FrameError(ValueError):
    """The bytes are not a LoRaWAN uplink this codec reads."""


@dataclass(frozen=True, slots=True)
class Credentials:
    """A tracker's LP0 session: its address as printed (big-endian hex) and its two keys."""

    dev_addr: str
    app_s_key: bytes
    nwk_s_key: bytes

    def __post_init__(self) -> None:
        if len(self.app_s_key) != 16 or len(self.nwk_s_key) != 16:
            raise ValueError("a session key is 16 bytes")
        if len(self.dev_addr) != 8:
            raise ValueError("a DevAddr is 8 hex digits")


@dataclass(frozen=True, slots=True)
class Uplink:
    mhdr: int
    dev_addr: str
    f_ctrl: int
    f_cnt: int
    f_opts: bytes
    f_port: int | None
    frm_payload: bytes
    mic: bytes
    #: MHDR and the MACPayload, what the MIC covers.
    signed: bytes

    @property
    def confirmed(self) -> bool:
        return self.mhdr == MHDR_CONFIRMED_UP


def parse_uplink(phy: bytes) -> Uplink:
    """Split a PHYPayload; raises `FrameError` when it is not an uplink or is too short."""
    if len(phy) < 1 + FHDR_FIXED_BYTES + MIC_BYTES:
        raise FrameError(f"frame of {len(phy)} bytes is shorter than a LoRaWAN uplink")
    mhdr = phy[0]
    if mhdr not in (MHDR_UNCONFIRMED_UP, MHDR_CONFIRMED_UP):
        raise FrameError(f"MHDR 0x{mhdr:02X} is not a LoRaWAN 1.0 data uplink")
    mac = phy[1:-MIC_BYTES]
    f_ctrl = mac[4]
    f_opts_len = f_ctrl & 0x0F
    if len(mac) < FHDR_FIXED_BYTES + f_opts_len:
        raise FrameError("frame is shorter than its FOpts length says")
    body = mac[FHDR_FIXED_BYTES + f_opts_len :]
    f_port = body[0] if body else None
    return Uplink(
        mhdr=mhdr,
        dev_addr=mac[0:4][::-1].hex().upper(),
        f_ctrl=f_ctrl,
        f_cnt=int.from_bytes(mac[5:7], "little"),
        f_opts=bytes(mac[FHDR_FIXED_BYTES : FHDR_FIXED_BYTES + f_opts_len]),
        f_port=f_port,
        frm_payload=bytes(body[1:]) if body else b"",
        mic=bytes(phy[-MIC_BYTES:]),
        signed=bytes(phy[:-MIC_BYTES]),
    )


def _block(prefix: int, dev_addr: str, f_cnt: int, last: int) -> bytes:
    """The A (0x01) and B0 (0x49) blocks of LoRaWAN 1.0: direction, DevAddr little-endian,
    the 32-bit counter little-endian, then the block index or the message length."""
    return (
        bytes([prefix, 0, 0, 0, 0, UPLINK])
        + bytes.fromhex(dev_addr)[::-1]
        + (f_cnt & 0xFFFFFFFF).to_bytes(4, "little")
        + bytes([0, last & 0xFF])
    )


def verify_mic(uplink: Uplink, nwk_s_key: bytes, *, f_cnt: int | None = None) -> bool:
    """Whether the MIC verifies under the key. `f_cnt` is the 32-bit counter; by default the
    frame's own 16 bits with the upper half zero, which is the mode the firmware uses."""
    count = uplink.f_cnt if f_cnt is None else f_cnt
    mac = CMAC(algorithms.AES(nwk_s_key))
    mac.update(_block(0x49, uplink.dev_addr, count, len(uplink.signed)) + uplink.signed)
    return mac.finalize()[:MIC_BYTES] == uplink.mic


def decrypt_payload(
    uplink: Uplink, app_s_key: bytes, nwk_s_key: bytes, *, f_cnt: int | None = None
) -> bytes:
    """The FRMPayload in the clear: AES-128 in the LoRaWAN counter construction under the
    AppSKey, or the NwkSKey on port 0 (MAC commands)."""
    if not uplink.frm_payload:
        return b""
    key = nwk_s_key if uplink.f_port == 0 else app_s_key
    count = uplink.f_cnt if f_cnt is None else f_cnt
    # ECB of the counter block is the LoRaWAN construction itself, not a mode choice of ours
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    out = bytearray()
    for index in range(0, len(uplink.frm_payload), 16):
        stream = encryptor.update(_block(0x01, uplink.dev_addr, count, index // 16 + 1))
        chunk = uplink.frm_payload[index : index + 16]
        out += bytes(a ^ b for a, b in zip(chunk, stream, strict=False))
    return bytes(out)


def build_uplink(
    credentials: Credentials, f_cnt: int, f_port: int, payload: bytes, *, f_opts: bytes = b""
) -> bytes:
    """A LoRaWAN 1.0 unconfirmed uplink the way the firmware's `lorawan_tools_build` and the
    public replay app's `make_test_log.py` build one: the inverse of `unwrap`, for the tests
    and the demo cards. The counter's 16 bits go in the header and the whole value into the
    blocks, which is the firmware's 16-bit mode when `f_cnt` is below 65536."""
    dev_addr_le = bytes.fromhex(credentials.dev_addr)[::-1]
    fhdr = dev_addr_le + bytes([len(f_opts) & 0x0F, f_cnt & 0xFF, (f_cnt >> 8) & 0xFF]) + f_opts
    key = credentials.nwk_s_key if f_port == 0 else credentials.app_s_key
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    encrypted = bytearray()
    for index in range(0, len(payload), 16):
        stream = encryptor.update(_block(0x01, credentials.dev_addr, f_cnt, index // 16 + 1))
        chunk = payload[index : index + 16]
        encrypted += bytes(a ^ b for a, b in zip(chunk, stream, strict=False))
    signed = bytes([MHDR_UNCONFIRMED_UP]) + fhdr + bytes([f_port]) + bytes(encrypted)
    mac = CMAC(algorithms.AES(credentials.nwk_s_key))
    mac.update(_block(0x49, credentials.dev_addr, f_cnt, len(signed)) + signed)
    return signed + mac.finalize()[:MIC_BYTES]


@dataclass(frozen=True, slots=True)
class Unwrapped:
    payload: bytes
    f_port: int | None
    #: The 32-bit counter the MIC verified under: the frame's 16 bits with the upper half the
    #: device was last seen at (or zero), as a LoRaWAN receiver reconstructs it.
    f_cnt: int


def counter_candidates(f_cnt16: int, last_f_cnt: int | None) -> list[int]:
    """The 32-bit counters a frame's 16 bits may stand for: with the upper half zero (the
    firmware's 16-bit mode), then with the upper half of the device's last verified counter
    and the one after it (a rollover). The MIC decides; nothing else is guessed."""
    uppers = [0]
    if last_f_cnt is not None:
        upper = last_f_cnt >> 16
        for candidate in (upper, upper + 1):
            if candidate not in uppers and candidate <= 0xFFFF:
                uppers.append(candidate)
    return [(upper << 16) | (f_cnt16 & 0xFFFF) for upper in uppers]


def unwrap(phy: bytes, credentials: Credentials, *, last_f_cnt: int | None = None) -> Unwrapped:
    """Verify and decrypt one stored frame with the tracker's keys: the application payload,
    its port and the counter it verified under. Raises `FrameError` when the address is
    another device's or the MIC verifies under no candidate counter, which is never guessed
    around."""
    uplink = parse_uplink(phy)
    if uplink.dev_addr != credentials.dev_addr.upper():
        raise FrameError(
            f"frame is addressed to {uplink.dev_addr}, the device holds {credentials.dev_addr}"
        )
    for f_cnt in counter_candidates(uplink.f_cnt, last_f_cnt):
        if verify_mic(uplink, credentials.nwk_s_key, f_cnt=f_cnt):
            payload = decrypt_payload(
                uplink, credentials.app_s_key, credentials.nwk_s_key, f_cnt=f_cnt
            )
            return Unwrapped(payload=payload, f_port=uplink.f_port, f_cnt=f_cnt)
    raise FrameError("the frame does not verify under this device's keys")
