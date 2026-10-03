FROM python:3.14.8-slim@sha256:89fb7d3da20043c370643435258bdd7ab755d326d359001d02988ed15ae5219e

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LIFETIME_DATA_DIR=/var/lib/lifetime

WORKDIR /app
COPY requirements-lock.txt /app/requirements-lock.txt
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-lock.txt \
    && python -m pip check \
    && groupadd --gid 10001 lifetime \
    && useradd --uid 10001 --gid 10001 --home-dir /var/lib/lifetime --no-create-home --shell /usr/sbin/nologin lifetime \
    && install -d -m 0700 -o 10001 -g 10001 /var/lib/lifetime

COPY VERSION /app/VERSION
COPY lifetime /app/lifetime
COPY migrations /app/migrations
COPY data/life_expectancy /app/data/life_expectancy

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2).read()"
# Migrations and import are explicit commands before startup. No access log;
# critical-only server logs avoid raw malformed request lines in warnings.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "30", "--forwarded-allow-ips", "", "--log-level", "critical", "--error-logfile", "-", "lifetime:create_app()"]
