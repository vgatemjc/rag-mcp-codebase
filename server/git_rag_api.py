"""
Deprecated entrypoint maintained for backward compatibility.

New deployments should import `server.app:create_app` or `server.main:app`.
"""

from server.app import create_app

app = create_app()
