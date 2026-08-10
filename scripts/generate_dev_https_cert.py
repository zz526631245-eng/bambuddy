"""Generate a local HTTPS certificate for phone camera testing.

The generated key/certificate live under data/dev_https (ignored by Git) and
are for local development only. They are not production credentials.
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _local_ips() -> set[str]:
    addresses = {"127.0.0.1"}
    try:
        addresses.add(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    return addresses


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ip", action="append", default=[])
    args = parser.parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    cert_path = output_dir / "bambuddy-dev.crt"
    key_path = output_dir / "bambuddy-dev.key"
    ips = _local_ips().union(args.ip)
    if cert_path.exists() and key_path.exists():
        print(f"certificate={cert_path}")
        print(f"key={key_path}")
        return

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Bambuddy local development")])
    san = [x509.IPAddress(ipaddress.ip_address(value)) for value in sorted(ips)]
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    print(f"certificate={cert_path}")
    print(f"key={key_path}")


if __name__ == "__main__":
    main()
