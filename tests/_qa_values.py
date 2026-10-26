"""Per-run random values for the QA suites.

No invented records: every identifier, phone number, host and signing value here
is generated fresh on each run. Hosts use the reserved .invalid TLD and phone
numbers use +999, which is not an assigned ITU country code.
"""

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
