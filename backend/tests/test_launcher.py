"""Exercise the user-facing launcher against real local listening sockets."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]


def test_repeat_start_reuses_healthy_service_and_exits_successfully():
    from app.runtime_identity import health_identity

    class Service(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(health_identity()).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Service)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT/'scripts/launch.py'), '--port', str(server.server_port), '--no-browser'],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=12,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'Already running' in result.stdout
        assert str(server.server_port) in result.stdout
        assert '10048' not in result.stderr
    finally:
        server.shutdown()
        server.server_close()


def test_busy_foreign_port_is_not_killed_or_reused():
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location('web_launcher', ROOT/'scripts/launch.py')
    launcher = module_from_spec(spec)
    spec.loader.exec_module(launcher)
    with socket.socket() as unrelated:
        unrelated.bind(('127.0.0.1', 0))
        unrelated.listen()
        port = unrelated.getsockname()[1]
        selected, reserved = launcher.reserve_or_reuse(port, attempts=5, probe_timeout=.1)
        try:
            assert selected != port
            assert reserved is not None
            with socket.socket() as check:
                assert check.connect_ex(('127.0.0.1', port)) == 0
            with socket.socket() as competitor:
                try:
                    competitor.bind(('127.0.0.1', selected))
                except OSError:
                    pass
                else:
                    raise AssertionError('The selected port was not reserved')
        finally:
            reserved.close()


def test_health_identifies_the_running_installation(client):
    response = client.get('/api/v1/health')
    assert response.json()['service'] == 'monitoring-web'
    assert len(response.json()['instance']) == 24


def test_lan_listener_is_bound_to_all_interfaces():
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location('web_launcher_lan', ROOT/'scripts/launch.py')
    launcher = module_from_spec(spec)
    spec.loader.exec_module(launcher)
    port, reserved = launcher.reserve_or_reuse(0, host='0.0.0.0')
    try:
        assert reserved.getsockname()[0] == '0.0.0.0'
    finally:
        reserved.close()


def test_lan_launch_does_not_reuse_a_local_only_server(monkeypatch):
    from importlib.util import module_from_spec, spec_from_file_location
    from app import chart_links
    spec = spec_from_file_location('web_launcher_local_only', ROOT/'scripts/launch.py')
    launcher = module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(chart_links, 'lan_addresses', lambda: ['192.168.1.4'])
    monkeypatch.setattr(launcher, 'is_our_service', lambda port, timeout=1, host='127.0.0.1': host == '127.0.0.1')
    with socket.socket() as local:
        if os.name == 'nt':
            local.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        local.bind(('127.0.0.1', 0))
        local.listen()
        port = local.getsockname()[1]
        selected, reserved = launcher.reserve_or_reuse(port, attempts=5, host='0.0.0.0')
        try:
            assert selected != port
            assert reserved is not None
            assert reserved.getsockname()[0] == '0.0.0.0'
        finally:
            reserved.close()
