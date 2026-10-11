"""Non-secret installation identity used by the local desktop launcher."""
import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTANCE = hashlib.sha256(os.path.normcase(str(ROOT)).encode('utf-8')).hexdigest()[:24]


def health_identity():
    return {'status': 'ok', 'version': '1.07', 'service': 'monitoring-web', 'instance': INSTANCE}
