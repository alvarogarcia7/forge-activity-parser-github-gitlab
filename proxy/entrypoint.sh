#!/bin/sh
# Turn /config/urls.txt (read-only mount) into a squid domain allowlist.
# Accepted line formats (comments with # and blank lines ignored):
#   github.com                    exact host
#   .github.com                   host and all subdomains
#   https://gitlab.com/some/path  URL -> host (path is ignored: HTTPS is tunnelled,
#                                 the proxy only ever sees host:port)
set -eu
SRC="${ALLOWLIST_FILE:-/config/urls.txt}"
DST=/run/squid/allowed_domains.txt

# A missing bind-mount source makes Docker create an empty *directory* at this path;
# refuse that explicitly instead of starting with an empty allowlist.
[ -f "$SRC" ] && [ -r "$SRC" ] || {
  echo "allowlist is not a readable regular file: $SRC" >&2
  echo "(if it is a directory, the host path was not visible to the Docker daemon)" >&2
  exit 1
}

sed -e 's/#.*//' -e 's/[[:space:]]//g' "$SRC" \
  | sed -E 's#^[a-zA-Z][a-zA-Z0-9+.-]*://##; s#[/?].*$##; s#^[^@]*@##; s#:[0-9]+$##' \
  | tr '[:upper:]' '[:lower:]' \
  | grep -v '^$' \
  | sort -u >"$DST"

if [ ! -s "$DST" ]; then
  echo "allowlist is empty: all egress will be denied" >&2
  echo ".invalid" >"$DST"   # squid refuses an empty dstdomain file
fi

echo "egress allowlist:" >&2
sed 's/^/  /' "$DST" >&2

squid -k parse -f /etc/squid/squid.conf >/dev/null 2>&1 \
  || { squid -k parse -f /etc/squid/squid.conf; exit 1; }
exec squid -N -f /etc/squid/squid.conf
