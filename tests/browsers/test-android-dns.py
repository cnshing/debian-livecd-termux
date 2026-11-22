#!/usr/bin/env python3
"""Exercise the glibc NSS ABI against a fragmented Android DNS wire fixture."""
import concurrent.futures
import ctypes as C
import errno
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'packages/bionilux/nss-android.c'
SETUP = ROOT / 'packages/bionilux/configure-dns'


def u32(n):
    return struct.pack('!I', n)


def string(value):
    data = value.encode() + b'\0' if value else b''
    return u32(len(data)) + data


def record(family, address, canonical='', scope=0):
    raw = socket.inet_pton(family, address)
    sockaddr = struct.pack('=H', family) + b'\0\0'
    if family == socket.AF_INET:
        sockaddr += raw + bytes(8)
    else:
        sockaddr += bytes(4) + raw + struct.pack('=I', scope)
    return b''.join(u32(n) for n in (1, 2, family, 1, 6, len(sockaddr))) + sockaddr + string(canonical)


class Host(C.Structure):
    _fields_ = [('name', C.c_char_p), ('aliases', C.POINTER(C.c_char_p)),
                ('family', C.c_int), ('length', C.c_int), ('addresses', C.POINTER(C.c_void_p))]


class Tuple(C.Structure):
    pass


Tuple._fields_ = [('next', C.POINTER(Tuple)), ('name', C.c_char_p), ('family', C.c_int),
                 ('addr', C.c_uint32 * 4), ('scope', C.c_uint32)]


class ResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='nss-android-')
        cls.path = Path(cls.tmp.name)
        cls.sock = str(cls.path / 'dns')
        library = cls.path / 'libnss_android.so.2'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        f'-DANDROID_DNS_SOCKET="{cls.sock}"', str(SOURCE), '-o', str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.host = cls.lib._nss_android_gethostbyname3_r
        cls.host.argtypes = [C.c_char_p, C.c_int, C.POINTER(Host), C.c_void_p, C.c_size_t,
                             C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int32),
                             C.POINTER(C.c_char_p)]
        cls.tuples = cls.lib._nss_android_gethostbyname4_r
        cls.tuples.argtypes = [C.c_char_p, C.POINTER(C.POINTER(Tuple)), C.c_void_p, C.c_size_t,
                               C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int32)]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fixture(self, payload, action, count=1):
        commands = []
        errors = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(self.sock)
            server.listen(16)
            server.settimeout(5)

            def respond():
                try:
                    for _ in range(count):
                        conn, _ = server.accept()
                        with conn:
                            command = b''
                            while not command.endswith(b'\0'):
                                chunk = conn.recv(4096)
                                if not chunk:
                                    raise AssertionError('unterminated command')
                                command += chunk
                            commands.append(command)
                            # recv must handle partial fields, including the status code.
                            try:
                                for i in range(0, len(payload), 3):
                                    conn.sendall(payload[i:i+3])
                            except BrokenPipeError:
                                pass  # Expected for malformed/oversized payloads.
                except Exception as exc:
                    errors.append(exc)

            worker = threading.Thread(target=respond)
            worker.start()
            try:
                result = action()
            finally:
                worker.join(8)
                os.unlink(self.sock)
            self.assertFalse(worker.is_alive())
            if errors:
                raise errors[0]
        return result, commands

    def resolve(self, family=socket.AF_INET, size=4096, name=b'host.test'):
        result, err, herr, ttl, canonical = Host(), C.c_int(), C.c_int(), C.c_int32(-1), C.c_char_p()
        # Deliberately unaligned NSS buffer.
        storage = C.create_string_buffer(size + 1)
        status = self.host(name, family, C.byref(result), C.addressof(storage) + 1, size,
                           C.byref(err), C.byref(herr), C.byref(ttl), C.byref(canonical))
        addresses = []
        if status == 1:
            i = 0
            while result.addresses[i]:
                addresses.append(socket.inet_ntop(family, C.string_at(result.addresses[i], result.length)))
                i += 1
        return status, err.value, herr.value, addresses, canonical.value, ttl.value

    def test_ipv4_canonical_and_multiple_addresses(self):
        payload = b'222\0' + record(2, '192.0.2.25', 'canonical.test') + record(2, '192.0.2.26') + u32(0)
        result, commands = self.fixture(payload, self.resolve)
        self.assertEqual(result, (1, 0, 0, ['192.0.2.25', '192.0.2.26'], b'canonical.test', 0))
        self.assertEqual(commands, [b'getaddrinfo host.test ^ 2 2 1 6 0\0'])

    def test_ipv6(self):
        result, _ = self.fixture(b'222\0' + record(10, '2001:db8::25') + u32(0), lambda: self.resolve(10))
        self.assertEqual(result[3], ['2001:db8::25'])

    def test_unspec_tuples_and_existing_first_tuple(self):
        def resolve(existing):
            first = Tuple()
            result = C.pointer(first) if existing else C.POINTER(Tuple)()
            storage = C.create_string_buffer(4097)
            err, herr, ttl = C.c_int(), C.c_int(), C.c_int32(-1)
            status = self.tuples(b'host.test', C.byref(result), C.addressof(storage) + 1, 4096,
                                 C.byref(err), C.byref(herr), C.byref(ttl))
            self.assertEqual(status, 1)
            found = []
            while result:
                t = result.contents
                found.append((t.family, socket.inet_ntop(t.family, bytes(t.addr)[:4 if t.family == 2 else 16]), t.scope))
                result = t.next
            self.assertEqual(found, [(10, 'fe80::25', 3), (2, '192.0.2.25', 0)])
        payload = b'222\0' + record(10, 'fe80::25', scope=3) + record(2, '192.0.2.25') + u32(0)
        for existing in (False, True):
            self.fixture(payload, lambda: resolve(existing))

    def test_retryable_small_buffer(self):
        result, _ = self.fixture(b'222\0' + record(2, '192.0.2.25') + u32(0), lambda: self.resolve(size=4))
        self.assertEqual(result[:3], (-2, errno.ERANGE, -1))

    def test_negative_and_transient_answers(self):
        for error, status in [(7, 0), (8, 0), (2, -2), (4, -2), (6, -2)]:
            result, _ = self.fixture(b'401\0' + u32(4) + struct.pack('=i', error), self.resolve)
            self.assertEqual(result[0], status)

    def test_empty_answer(self):
        result, _ = self.fixture(b'222\0' + u32(0), self.resolve)
        self.assertEqual(result[0], 0)

    def test_truncated_and_oversized_response(self):
        for payload in (b'222\0' + u32(1), b'222\0' + b''.join(u32(n) for n in (1, 0, 2, 1, 6, 9999))):
            result, _ = self.fixture(payload, self.resolve)
            self.assertEqual(result[0], -2)

    def test_command_injection_and_unsupported_family(self):
        for name in (b'host.test\nother', b'host test', b'^', b'"host"', b''):
            self.assertEqual(self.resolve(name=name)[0], 0)
        self.assertEqual(self.resolve(family=123)[0], -1)

    def test_parallel_requests(self):
        def run():
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                return list(pool.map(lambda _: self.resolve(), range(8)))
        results, commands = self.fixture(b'222\0' + record(2, '192.0.2.25') + u32(0), run, count=8)
        self.assertEqual(len(commands), 8)
        self.assertTrue(all(r[0] == 1 and r[3] == ['192.0.2.25'] for r in results))

    def test_reverse(self):
        def reverse():
            function = self.lib._nss_android_gethostbyaddr_r
            function.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.POINTER(Host), C.c_void_p,
                                 C.c_size_t, C.POINTER(C.c_int), C.POINTER(C.c_int)]
            storage = C.create_string_buffer(4096)
            result, err, herr = Host(), C.c_int(), C.c_int()
            status = function(socket.inet_pton(2, '192.0.2.25'), 4, 2, C.byref(result), storage,
                              len(storage), C.byref(err), C.byref(herr))
            self.assertEqual((status, result.name), (1, b'canonical.test'))
        payload = b'222\0' + string('canonical.test') + string('alias.test') + u32(0)
        payload += u32(2) + u32(4) + u32(16) + socket.inet_pton(2, '192.0.2.25') + bytes(12) + u32(0)
        _, commands = self.fixture(payload, reverse)
        self.assertEqual(commands, [b'gethostbyaddr 192.0.2.25 4 2 0\0'])


class ConfigurationTests(unittest.TestCase):
    def test_symlink_and_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'custom.conf'
            target.write_text('passwd: files\nhosts: files dns\n')
            link = root / 'glibc/etc/nsswitch.conf'
            link.parent.mkdir(parents=True)
            link.symlink_to(target)
            env = {**os.environ, 'PREFIX': directory}
            subprocess.run(['sh', str(SETUP)], env=env, check=True)
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(), 'passwd: files\nhosts: files android\n')
            subprocess.run(['sh', str(SETUP), '--remove'], env=env, check=True)
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(), 'passwd: files\nhosts: files dns\n')

    def test_default_upgrade_custom_preservation_and_idempotence(self):
        for original, expected in [(None, 'hosts: files android\n'),
                ('passwd: files\nhosts: files dns\n', 'passwd: files\nhosts: files android\n'),
                ('hosts: files dns # default\n', 'hosts: files android\n'),
                ('hosts: files custom dns\n', 'hosts: files custom dns\n')]:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as directory:
                conf = Path(directory) / 'glibc/etc/nsswitch.conf'
                conf.parent.mkdir(parents=True)
                if original is not None:
                    conf.write_text(original)
                for _ in range(2):
                    subprocess.run(['sh', str(SETUP)], env={**os.environ, 'PREFIX': directory},
                                   check=True, capture_output=True)
                    self.assertEqual(conf.read_text(), expected)


if __name__ == '__main__':
    unittest.main()
