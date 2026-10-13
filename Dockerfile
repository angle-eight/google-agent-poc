FROM ghcr.io/astral-sh/uv:0.7.2 AS uv
FROM python:3.13-slim

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY helpdesk ./helpdesk
COPY main.py ./
RUN useradd --uid 10001 --create-home appuser
USER appuser
EXPOSE 8080
CMD ["python", "main.py"]
