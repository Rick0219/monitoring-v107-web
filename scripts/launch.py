"""Reuse an existing instance, or reserve a free port and open the ready app."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.runtime_identity import health_identity


def is_our_service(port, timeout=1, host='127.0.0.1'):
    try:
        # A system HTTP proxy must not intercept the local readiness check.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://{host}:{port}/api/v1/health', timeout=timeout) as response:
            result = json.loads(response.read(2048))
        return result == health_identity()
    except (OSError, ValueError):
        return False


def reserve_or_reuse(preferred, attempts=20, probe_timeout=1, host='127.0.0.1'):
    for port in range(preferred, min(65536, preferred + attempts)):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == 'nt':
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((host, port))
            return port, listener
        except OSError:
            listener.close()
            if is_our_service(port, probe_timeout):
                if host == '0.0.0.0':
                    from app.chart_links import lan_addresses
                    addresses = lan_addresses()
                    if not addresses or not is_our_service(port, probe_timeout, addresses[0]):
                        continue
                return port, None
    raise RuntimeError('No available local port. Close an unused service or specify -Port with another port.')


def open_page(url):
    try:
        if not webbrowser.open(url):
            print('Browser could not be opened automatically. Please copy this address:', url, flush=True)
    except OSError:
        print('Please open this address in your browser:', url, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8007)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--host', choices=['127.0.0.1', '0.0.0.0'], default='127.0.0.1')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Port must be between 1024 and 65535')
    os.environ['WEB_BIND_HOST'] = args.host
    port, listener = reserve_or_reuse(args.port, host=args.host)
    url = f'http://127.0.0.1:{port}/login'
    if listener is None:
        print('Already running. Opening the existing service:', url, flush=True)
        if not args.no_browser:
            open_page(url)
        return 0
    if port != args.port:
        print(f'Port {args.port} is occupied. Using {port}; no existing program was stopped.', flush=True)

    os.chdir(ROOT / 'backend')
    import uvicorn
    server = uvicorn.Server(uvicorn.Config('app.main:app', host=args.host, port=port))
    finished = threading.Event()

    def when_ready():
        # Server.started is set after application startup and socket listening.
        while not finished.wait(.2):
            if server.started and is_our_service(port):
                print('Ready:', url, '\nKeep this window open. Press Ctrl+C to stop.', flush=True)
                if args.host == '0.0.0.0':
                    from app.chart_links import lan_addresses
                    for address in lan_addresses():
                        print(f'Phone / LAN: http://{address}:{port}/login', flush=True)
                if not args.no_browser:
                    open_page(url)
                return

    worker = threading.Thread(target=when_ready, daemon=True)
    worker.start()
    try:
        server.run(sockets=[listener])
        return 0 if server.started else 1
    finally:
        finished.set()
        worker.join(timeout=2)
        listener.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as exc:
        print('Startup failed:', exc, file=sys.stderr)
        sys.exit(1)
