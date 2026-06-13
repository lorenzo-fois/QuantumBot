#!/usr/bin/env bash
set -euo pipefail

python3 -m PyInstaller --clean --onedir --windowed --name "QuantumBot" QuantumBot.py
