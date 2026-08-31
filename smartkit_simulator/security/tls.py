"""Self-signed TLS certificate generation for the REST HTTPS simulator."""

import datetime
import ipaddress
import os
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from ..settings import local_ipv4_addresses


def ensure_rest_certificate(state):
    if os.path.exists(state.rest_cert_path) and os.path.exists(state.rest_key_path):
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "SmartKit REST Simulator"),
    ])
    san_entries = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname()),
                   x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    san_entries.extend(x509.IPAddress(ipaddress.ip_address(address))
                       for address in local_ipv4_addresses())
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(subject).issuer_name(issuer).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
            .sign(key, hashes.SHA256()))
    with open(state.rest_key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    with open(state.rest_cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def create_rest_tls_context(state):
    ensure_rest_certificate(state)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(state.rest_cert_path, state.rest_key_path)
    return context
