#!/usr/bin/env bash
# Builds the CVs into dist/ (in Docker).
#   ./run.sh                 every CV: yours (data/, if any) and the example (example/, if any)
#   ./run.sh <cv> [pt|en]    only one CV (a quick test)
#   ./run.sh test            the tests (tests/)
set -e
cd "$(dirname "$0")"
[ -t 0 ] && tty="" || tty="-T"     # no terminal (e.g. GitHub Actions): no TTY
build() { docker compose run --rm $tty cv python scripts/build.py "$@"; }

if [ "$1" = test ]; then
    docker compose run --rm $tty cv python -m unittest discover -s tests -v
    exit
fi
if [ $# -gt 0 ]; then
    build "$@"
    exit
fi
rm -rf dist
[ -d data ] && build all
if [ -d example ]; then build all --example; fi
