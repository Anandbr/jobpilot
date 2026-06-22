"""
Metrics infrastructure layer for JobPilot.

This file provides:
1. start_metrics_server() - call once at startup
2. Shared helpers used by multiple modules

Each module defines its own mwtrics close to where they're used.
"""


import os
import logging
from prometheus_client import start_http_server

logger = logging.getLogger(__name__)

METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))

def start_metrics_server():
    """
    Start the HTTP server that exposes /metrics for Prometheus.
    Call once at JobPilot startup before the main loop.
    
    Prometheus will scrape http://localhost:8000/metrics
    every 15 seconds and record all metrics defined anywhere
    in the codebase - prometheus_client automatically registers
    every metric regardless of which file defines it.
    """
    try:
        start_http_server(METRICS_PORT)
        print(f" [METRICS] Metrics available at "
              f"http://localhost:{METRICS_PORT}/metrics")
    except OSError as e:
        logger.warning(f" [METRICS] Could not start metrics server: {e}")
        print(f" [METRICS WARNING] Metrics server not started: {e}")