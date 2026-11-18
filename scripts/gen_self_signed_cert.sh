#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/deploy/certs"
mkdir -p "$DIR"

export MSYS_NO_PATHCONV=1
DIR_WIN="$(cygpath -m "$DIR")"

openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
  -keyout "$DIR_WIN/server.key" \
  -out "$DIR_WIN/server.crt" \
  -subj "/C=CN/O=VeriFix/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

chmod 600 "$DIR/server.key"
echo "certificate written: $DIR/server.crt"