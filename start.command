#!/bin/sh
set -eu
cd "$(dirname "$0")"
PORT="${PORT:-4173}"
if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  open "http://localhost:$PORT/"
  exit 0
fi

# Serve with no-cache headers so the browser always loads the latest app.js and styles.css.
/usr/bin/python3 -c '
import http.server, sys
class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()
http.server.ThreadingHTTPServer(("", int(sys.argv[1])), NoCache).serve_forever()
' "$PORT" >/tmp/roll-call-server.log 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT INT TERM

attempt=0
while ! /usr/bin/curl -fsS "http://127.0.0.1:$PORT/" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 50 ]; then
    echo "Could not start Roll Call on port $PORT."
    cat /tmp/roll-call-server.log
    exit 1
  fi
  /bin/sleep 0.1
done

open "http://localhost:$PORT/"
wait "$server_pid"
