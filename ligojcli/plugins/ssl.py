#!/usr/bin/env python3

import os
import re
import subprocess
import sys
import tempfile


def main():
    """
    A script to fetch the certificate chain from a given domain using only keytool
    and import or replace them in a Java truststore (JKS).

    Usage:
      python add_cert_to_jks.py <domain> [port=443] [keystore=truststore.jks] [password=changeit]
    """

    # Parse arguments
    if len(sys.argv) < 2:
        print("Usage: {} <domain> [port=443] [keystore=truststore.jks] [password=changeit]".format(sys.argv[0]))
        sys.exit(1)

    domain = sys.argv[1]
    port = sys.argv[2] if len(sys.argv) > 2 else "443"
    keystore = sys.argv[3] if len(sys.argv) > 3 else "truststore.jks"
    password = sys.argv[4] if len(sys.argv) > 4 else "changeit"

    # 1. Fetch the full certificate chain with keytool
    print(f"[*] Retrieving certificate chain from {domain}:{port} using keytool...")
    cmd = [
        "keytool", 
        "-printcert", 
        "-rfc",
        "-sslserver", f"{domain}:{port}"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print("[!] Failed to retrieve certificate chain. Error:")
        print(e.stderr)
        sys.exit(1)

    # 2. Extract the certificates from keytool output
    # keytool output includes lines like:
    #   -----BEGIN CERTIFICATE-----
    #   ...
    #   -----END CERTIFICATE-----
    #
    # Possibly repeated for multiple certificates in the chain.
    output = result.stdout

    # Use a regex to capture all blocks of -----BEGIN CERTIFICATE----- ... -----END CERTIFICATE-----
    cert_pattern = re.compile(
        r"(-+BEGIN CERTIFICATE-+[\r\n]+(?:[A-Za-z0-9+/\r\n=]+)+-+END CERTIFICATE-+)", 
        re.MULTILINE
    )
    certificates = cert_pattern.findall(output)

    if not certificates:
        print("[!] No certificates found in the keytool output. Aborting.")
        sys.exit(1)

    print(f"[*] Found {len(certificates)} certificate(s) in the chain.")

    # 3. Check if keystore exists; if not, create it
    if not os.path.isfile(keystore):
        print(f"[*] Keystore '{keystore}' not found. Creating a new one...")
        create_keystore(keystore, password)
        print(f"[*] Created new keystore: {keystore}")

    # 4. Import each certificate into the truststore
    for index, cert_pem in enumerate(certificates):
        alias = f"{domain.replace('.', '_')}_cert_{index}"
        import_certificate(keystore, password, alias, cert_pem)

    print(f"[*] Successfully imported {len(certificates)} certificates into '{keystore}'.")
    print(f"keytool -list -v -keystore {keystore} -storepass {password}")
    # 

def create_keystore(keystore, password):
    """
    Create a new empty JKS truststore by generating (and removing) a temporary key.
    """
    subprocess.run([
        "keytool", 
        "-genkeypair",
        "-alias", "tempkey",
        "-keystore", keystore,
        "-storepass", password,
        "-keypass", password,
        "-dname", "CN=Temporary Key, OU=NA, O=NA, L=NA, ST=NA, C=NA",
        "-keyalg", "RSA",
        "-keysize", "2048",
        "-validity", "365"
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Now remove the temporary key
    subprocess.run([
        "keytool", 
        "-delete",
        "-alias", "tempkey",
        "-keystore", keystore,
        "-storepass", password
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def import_certificate(keystore, password, alias, cert_pem):
    """
    Import (or replace) a certificate in the given keystore under the specified alias.
    """
    # 1. Check if alias exists
    alias_exists = False
    check_cmd = [
        "keytool",
        "-list",
        "-keystore", keystore,
        "-storepass", password,
        "-alias", alias
    ]
    result = subprocess.run(check_cmd, capture_output=True, text=True)
    if result.returncode == 0:
        alias_exists = True

    # 2. If alias exists, remove it to replace the certificate
    if alias_exists:
        print(f"[*] Alias '{alias}' already exists. Removing old entry...")
        delete_cmd = [
            "keytool",
            "-delete",
            "-alias", alias,
            "-keystore", keystore,
            "-storepass", password
        ]
        subprocess.run(delete_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 3. Write the certificate PEM to a temporary file
    with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
        tmp.write(cert_pem + "\n")
        tmp_cert_file = tmp.name

    # 4. Import the certificate
    print(f"[*] Importing certificate with alias '{alias}'...")
    import_cmd = [
        "keytool",
        "-importcert",
        "-noprompt",
        "-alias", alias,
        "-keystore", keystore,
        "-storepass", password,
        "-file", tmp_cert_file
    ]
    try:
        subprocess.run(import_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"[!] Failed to import certificate for alias '{alias}': {e}")
    finally:
        # Clean up temp file
        os.remove(tmp_cert_file)


if __name__ == "__main__":
    main()