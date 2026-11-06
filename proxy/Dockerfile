# syntax=docker/dockerfile:1.7
FROM alpine:3.22

RUN --mount=type=cache,target=/var/cache/apk,sharing=locked \
    apk add squid

COPY --chmod=0644 squid.conf /etc/squid/squid.conf
COPY --chmod=0755 entrypoint.sh /usr/local/bin/entrypoint.sh

# squid package already creates the unprivileged 'squid' user; run as it.
# Writable runtime state goes to /run/squid (tmpfs in compose).
RUN mkdir -p /run/squid && chown squid:squid /run/squid
USER squid
EXPOSE 3128
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
