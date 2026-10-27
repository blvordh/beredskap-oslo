#!/bin/bash
# Kjører innsamleren én gang fra Mac-en. Bruk: bash ~/Claude/beredskap/beredskap-oslo/kjor.sh
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Lager virtuelt Python-miljø (.venv) ..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
python -m collector -v --config config.yaml 2>&1 | tee data/kjorelogg.txt
echo
echo "Ferdig. Se data/status.json og data/kjorelogg.txt"
