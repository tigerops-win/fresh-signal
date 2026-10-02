#!/bin/bash
# FreshSignal local run
cd "$(dirname "$0")"
PORT="${PORT:-8000}" BIND="${BIND:-127.0.0.1}" python3 server.py
