"""Synthetic configuration for offline unit tests; no seller credentials required."""
import os

for key, value in {
    "WB_API_TOKEN": "test-token",
    "WB_API_KEY": "test-token",
    "DB_HOST": "localhost",
    "DB_NAME": "test_wb",
    "DB_USER": "test_user",
    "DB_PASSWORD": "test-password",
}.items():
    os.environ[key] = value
