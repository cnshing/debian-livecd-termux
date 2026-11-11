"""Validate pinned browser archives without modifying their signatures."""
import json
from pathlib import Path
import struct
import sys
import zipfile


def validate(path, browser, identifier, version):
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
    if manifest['version'] != version:
        raise ValueError(f"Expected {version}, got {manifest['version']}")
    if browser == 'firefox':
        settings = manifest.get('browser_specific_settings', manifest.get('applications', {}))
        actual = settings.get('gecko', {}).get('id')
    else:
        with Path(path).open('rb') as stream:
            magic, crx_version, header_size = struct.unpack('<4sII', stream.read(12))
            if magic != b'Cr24' or crx_version != 3:
                raise ValueError('Expected a CRX3 archive')
            header = stream.read(header_size)
        # CRX3 signed_header_data contains the 16-byte crx_id (protobuf field 1).
        crx_id = bytes.fromhex(identifier.translate(str.maketrans('abcdefghijklmnop', '0123456789abcdef')))
        if b'\x0a\x10' + crx_id not in header:
            raise ValueError('CRX header does not contain the expected extension ID')
        actual = identifier
    if actual != identifier:
        raise ValueError(f'Expected extension ID {identifier}, got {actual}')


if __name__ == '__main__':
    validate(*sys.argv[1:])
