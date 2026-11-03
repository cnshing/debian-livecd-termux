#!/usr/bin/env python3
"""Check Serein's built TLS dependencies against public roots and a local bad certificate."""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'synthetic TLS fixture\n')

    def log_message(self, *args):
        pass


def run(binary):
    with tempfile.TemporaryDirectory(prefix='serein-tls-') as temporary:
        root = Path(temporary)
        cert, key = root / 'cert.pem', root / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
                        '-addext', 'basicConstraints=critical,CA:FALSE'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        with HTTPServer(('127.0.0.1', 0), Fixture) as server:
            server.socket = context.wrap_socket(server.socket, server_side=True)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                subprocess.run([str(binary),
                    'https://raw.githubusercontent.com/ViceVerse-cz/Serein/'
                    'v1.0.0-nightly.20261028.68/README.md',
                    f'https://localhost:{server.server_port}/'], check=True, timeout=50)
            finally:
                server.shutdown()
                worker.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path, help='Built tls-probe.rs for this machine')
    run(parser.parse_args().binary.resolve())
