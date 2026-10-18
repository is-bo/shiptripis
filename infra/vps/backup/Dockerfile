# syntax=docker/dockerfile:1
FROM restic/restic:0.18.0@sha256:4cf4a61ef9786f4de53e9de8c8f5c040f33830eb0a10bf3d614410ee2fcb6120 AS restic
FROM postgres:16-alpine@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea
RUN addgroup -g 10001 wacla-backup && adduser -D -H -u 10001 -G wacla-backup wacla-backup \
    && mkdir -p /status /work /repository \
    && chown 10001:10001 /status /work /repository
COPY --from=restic /usr/bin/restic /usr/local/bin/restic
COPY --chmod=0644 backup/backup.sh /usr/local/bin/wacla-backup
ENV HOME=/tmp RESTIC_CACHE_DIR=/tmp/restic-cache
USER 10001:10001
ENTRYPOINT ["/bin/sh", "/usr/local/bin/wacla-backup"]
CMD ["backup"]
