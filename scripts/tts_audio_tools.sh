#!/bin/bash
# ffmpeg lives inside the napcat container; host has none. Small wrapper so we can
# probe/trim TTS clips without installing anything on the host.
set -u
CTR=${CTR:-napcat-qq}

probe() {
  docker cp "$1" "$CTR":/tmp/probe.mp3 >/dev/null
  echo -n "$1 duration="
  docker exec "$CTR" ffprobe -v error -show_entries format=duration -of csv=p=0 /tmp/probe.mp3
  docker exec "$CTR" ffmpeg -hide_banner -nostats -i /tmp/probe.mp3 \
    -af silencedetect=noise=-40dB:d=0.4 -f null - 2>&1 | grep -E 'silence_(start|end)'
}

# trim <src> <dst> [max_seconds] [pause] : cap every silence (incl. lead/tail) at `pause`
# seconds, then cap total length. CosyVoice wants ~8-10s refs with short pauses.
trim() {
  local src=$1 dst=$2 maxs=${3:-10} pause=${4:-0.4}
  docker cp "$src" "$CTR":/tmp/in.mp3 >/dev/null
  docker exec "$CTR" ffmpeg -hide_banner -loglevel error -y -i /tmp/in.mp3 \
    -af "silenceremove=stop_periods=-1:stop_duration=${pause}:stop_threshold=-40dB:detection=peak" \
    -t "$maxs" -c:a libmp3lame -b:a 192k /tmp/out.mp3
  docker cp "$CTR":/tmp/out.mp3 "$dst" >/dev/null
  echo -n "$dst duration="
  docker exec "$CTR" ffprobe -v error -show_entries format=duration -of csv=p=0 /tmp/out.mp3
}

"$@"
