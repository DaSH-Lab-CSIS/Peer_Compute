#!/usr/bin/env bash
set -e

BUILDS=(
  "020:peercompute/benchmark.020.network-benchmark.python-3.9"
  "501:peercompute/benchmark.501.graph-pagerank-3.9"
  "502:peercompute/benchmark.502.graph-mst-3.9"
  "503:peercompute/benchmark.503.graph-bfs-3.9"
  "504_svc25:peercompute/benchmark.504.graph-bfs-3.9"
  # 2026-10-08: native arm64 builds for services that failed on ARM providers
  # (amd64-only images crash under QEMU on the Pi 5's 16 KB-page kernel), and
  # 040 with an in-container reply peer. 020 above now has an in-container UDP echo peer.
  "040:peercompute/benchmark.040.server-reply.python-3.9"
  "210:peercompute/benchmark.210.thumbnailer.python-3.9"
  "504_dna:peercompute/benchmark.504.dna-visualisation.python-3.9"
)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Create a multi-platform builder if not already present
if ! docker buildx inspect multiarch-builder &>/dev/null; then
  docker buildx create --name multiarch-builder --driver docker-container --use
else
  docker buildx use multiarch-builder
fi
docker buildx inspect --bootstrap

for entry in "${BUILDS[@]}"; do
  dir="${entry%%:*}"
  tag="${entry##*:}"
  # Optional args: only build these dirs, e.g. ./build_and_push.sh 020 040
  if [ $# -gt 0 ] && [[ ! " $* " =~ " $dir " ]]; then continue; fi
  echo ""
  echo "=== Building $tag from $dir ==="
  docker buildx build \
    --platform linux/amd64,linux/arm64 \
    -t "$tag" \
    --push \
    "$SCRIPT_DIR/$dir"
done

echo ""
echo "All images built and pushed."
