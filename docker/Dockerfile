FROM ghcr.io/maki-it/python:debian as base

####################
# Python dependencies
####################
FROM base AS python-deps

USER 0

COPY Pipfile Pipfile.lock ./

RUN apt update && \
    apt install -y --no-install-recommends libpq-dev python3-dev gcc && \
    pipenv requirements > requirements.txt && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt

####################
# Final build stage
####################
FROM base AS runtime

ARG VERSION \
    BUILDTIME \
    REVISION \
    SOURCE_URL

ENV APP_LOGLEVEL=info \
    APP_FOO=BAR

USER 0

COPY --from=python-deps /install /usr/local

# Copy python modules from builder to app

COPY docker/docker-entrypoint.sh app/ ./

RUN chmod +x docker-entrypoint.sh && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 80

CMD ["python", "main.py"]
ENTRYPOINT ["/app/docker-entrypoint.sh"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --start-interval=5s --retries=3 \
    CMD /usr/bin/test -f /app/health.txt && rm /app/health.txt || exit 1
STOPSIGNAL SIGINT
