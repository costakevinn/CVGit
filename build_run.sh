#!/usr/bin/env bash
# Builds (or rebuilds) the Docker image, then runs ./run.sh with the same arguments.
#   ./build_run.sh           first time, or after changing the Dockerfile
set -e
cd "$(dirname "$0")"
docker compose build
./run.sh "$@"
