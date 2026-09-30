"""Verified updater HTTPS using the public CA roots shipped with the application.

Frozen Python must not depend on OpenSSL CA-file paths from its build machine.
PyInstaller's certifi hook collects cacert.pem; an explicit CA file also avoids
dependence on SSL_CERT_FILE/SSL_CERT_DIR or a user's Python installation.
"""
import ssl

import certifi


def https_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=certifi.where())
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError("Updater HTTPS requires certificate and hostname verification")
    return context
