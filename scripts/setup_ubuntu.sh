#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cat <<'EOF'
Ubuntu / WSL prerequisites expected by this project:
  python3-venv
  python3-pip
  python3-dev
  build-essential
  pkg-config
  libcairo2-dev
  libgirepository1.0-dev
  gir1.2-rsvg-2.0

Graphics tools currently present in the target WSL environment and useful for source-asset prep:
  gimp
  inkscape
  rsvg-convert

If they are missing, install them with:
  sudo apt-get update
  sudo apt-get install -y python3-venv python3-pip python3-dev build-essential pkg-config libcairo2-dev libgirepository1.0-dev gir1.2-rsvg-2.0
EOF

python3 -m venv "${ROOT_DIR}/.venv"
source "${ROOT_DIR}/.venv/bin/activate"
python -m pip install --upgrade pip
python -m pip install -e "${ROOT_DIR}[dev]"

echo
echo "Environment ready."
echo "Activate with: source ${ROOT_DIR}/.venv/bin/activate"
