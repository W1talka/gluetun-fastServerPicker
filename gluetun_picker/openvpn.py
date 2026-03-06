from __future__ import annotations

from pathlib import Path

from .models import ProbeSpec


PRIVADO_CA_CERT = (
    "MIIFKDCCAxCgAwIBAgIJAMtrmqZxIV/OMA0GCSqGSIb3DQEBDQUAMBIxEDAOBgNVBAMMB1ByaXZhZG8wHhcNMjAwMTA4"
    "MjEyODQ1WhcNMzUwMTA5MjEyODQ1WjASMRAwDgYDVQQDDAdQcml2YWRvMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKC"
    "AgEAxPwOgiwNJzZTnKIXwAB0TSu/Lu2qt2U2I8obtQjwhi/7OrfmbmYykSdro70al2XPhnwAGGdCxW6LDnp0UN/IOhD11mgBP"
    "o14f5CLkBQjSJ6VN5miPbvK746LsNZl9H8rQGvDuPo4CG9BfPZMiDRGlsMxij/jztzgT1gmuxQ7WHfFRcNzBas1dHa9hV/d3"
    "TU6/t47x4SE/ljdcCtJiu7Zn6ODKQoys3mB7Luz2ngqUJWvkqsg+E4+3eJ0M8Hlbn5TPaRJBID7DAdYo6Vs6xGCYr981ThFc"
    "moIQ10js10yANrrfGAzd03b3TnLAgko0uQMHjliMZL6L8sWOPHxyxJI0us88SFh4UgcFyRHKHPKux7w24SxAlZUYoUcTHp9Vj"
    "G5XvDKYxzgV2RdM4ulBGbQRQ3y3/CyddsyQYMvA55Ets0LfPaBvDIcct70iXijGsdvlX1du3ArGpG7Vaje/RU4nbbGT6HYRd"
    "t5YyZfof288ukMOSj20nVcmS+c/4tqsxSerRb1aq5LOi1IemSkTMeC5gCbexk+L1vl7NT/58sxjGmu5bXwnvev/lIItfi2Al"
    "ITrfUSEv19iDMKkeshwn/+sFJBMWYyluP+yJ56yR+MWoXvLlSWphLDTqq19yx3BZn0P1tgbXoR0g8PTdJFcz8z3RIb7myVLY"
    "ulV1oGG/3rka0CAwEAAaOBgDB+MB0GA1UdDgQWBBTFtJkZCVDuDAD6k5bJzefjJdO3DTBCBgNVHSMEOzA5gBTFtJkZCVDuDAD"
    "6k5bJzefjJdO3DaEWpBQwEjEQMA4GA1UEAwwHUHJpdmFkb4IJAMtrmqZxIV/OMAwGA1UdEwQFMAMBAf8wCwYDVR0PBAQDAgE"
    "GMA0GCSqGSIb3DQEBDQUAA4ICAQB7MUSXMeBb9wlSv4sUaT1JHEwE26nlBw+TKmezfuPU5pBlY0LYr6qQZY95DHqsRJ7ByUz"
    "GUrGo17dNGXlcuNc6TAaQQEDRPo6y+LVh2TWMk15TUMI+MkqryJtCret7xGvDigKYMJgBy58HN3RAVr1B7cL9youwzLgc2Y/"
    "NcFKvnQJKeiIYAJ7g0CcnJiQvgZTS7xdwkEBXfsngmUCIG320DLPEL+Ze0HiUrxwWljMRya6i40AeH3Zu2i532xX1wV5+cjA"
    "4RJWIKg6ri/Q54iFGtZrA9/nc6y9uoQHkmz8cGyVUmJxFzMrrIICVqUtVRxLhkTMe4UzwRWTBeGgtW4tS0yq1QonAKfOyjgR"
    "w/CeY55D2UGvnAFZdTadtYXS4Alu2P9zdwoEk3fzHiVmDjqfJVr5wz9383aABUFrPI3nz6ed/Z6LZflKh1k+DUDEp8NxU4k"
    "lUULWsSOKoa5zGX51G8cdHxwQLImXvtGuN5eSR8jCTgxFZhdps/xes4KkyfIz9FMYG748M+uOTgKITf4zdJ9BAyiQaOufVQZ"
    "8WjhWzWk9YHec9VqPkzpWNGkVjiRI5ewuXwZzZ164tMv2hikBXSuUCnFz37/ZNwGlDi0oBdDszCk2GxccdFHHaCSmpjU5Mrd"
    "J+5IhtTKGeTx+US2hTIVHQFIO99DmacxSYvLNcSQ=="
)


def write_openvpn_files(directory: Path, spec: ProbeSpec) -> tuple[Path, Path]:
    auth_path = directory / "auth.conf"
    config_path = directory / "privado.ovpn"
    auth_path.write_text(spec.username + "\n" + spec.password + "\n", encoding="utf-8")
    auth_path.chmod(0o600)
    config_path.write_text(build_privado_openvpn_config(auth_path, spec), encoding="utf-8")
    return config_path, auth_path


def build_privado_openvpn_config(auth_path: Path, spec: ProbeSpec) -> str:
    lines = [
        "client",
        "nobind",
        "tls-exit",
        "auth-nocache",
        "mute-replay-warnings",
        "auth-retry nointeract",
        "suppress-timestamps",
        "dev tun",
        f"verb {spec.openvpn_verbosity}",
        "proto udp",
        f"remote {spec.candidate.ip} 1194",
        f"auth-user-pass {auth_path}",
        'pull-filter ignore "auth-token"',
        "ping 10",
        f"verify-x509-name {spec.candidate.hostname} name",
        "tls-cipher TLS-DHE-RSA-WITH-AES-256-CBC-SHA:TLS-DHE-DSS-WITH-AES-256-CBC-SHA:TLS-RSA-WITH-AES-256-CBC-SHA",
        "data-ciphers-fallback AES-256-CBC",
        "data-ciphers AES-256-CBC",
        "auth SHA256",
        "mssfix 1320",
        "explicit-exit-notify",
        "<ca>",
        "-----BEGIN CERTIFICATE-----",
        PRIVADO_CA_CERT,
        "-----END CERTIFICATE-----",
        "</ca>",
    ]
    return "\n".join(lines) + "\n"
