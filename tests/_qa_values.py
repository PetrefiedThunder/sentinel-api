"""Per-run random values for the QA suites.

No invented records: every identifier, phone number, host and signing value here
is generated fresh on each run. Hosts use the reserved .invalid TLD and phone
numbers use +999, which is not an assigned ITU country code.
"""

import ipaddress
import secrets


def rhex(n: int = 8) -> str:
    return secrets.token_hex(n)


def rid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def rphone() -> str:
    return "+999" + "".join(str(secrets.randbelow(10)) for _ in range(9))


def rhost() -> str:
    return f"h{secrets.token_hex(6)}.invalid"


def rbase_url() -> str:
    return f"http://{rhost()}"


def remail() -> str:
    return f"{rhex()}@{rhost()}"


def rpublic_ip(version: int = 4) -> str:
    """A random globally routable address; it is only handed to a mocked resolver."""
    if version == 4:
        bits, low = 32, 0
    else:
        bits, low = 125, 0x2000 << 112  # 2000::/3, global unicast
    while True:
        address = ipaddress.ip_address(low + secrets.randbits(bits))
        if address.is_global and not address.is_multicast:
            return str(address)
