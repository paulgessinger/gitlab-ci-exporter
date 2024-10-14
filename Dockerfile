FROM python:3.12-slim-bookworm as builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12 \
    UV_PROJECT_ENVIRONMENT=/app

COPY pyproject.toml /_lock/
COPY uv.lock /_lock/

RUN cd /_lock \
  && uv sync \
    --locked \
    --no-dev \
    --no-install-project

COPY . /src
RUN uv pip install \
        --python=$UV_PROJECT_ENVIRONMENT \
        --no-deps \
        /src


FROM python:3.12-slim-bookworm
COPY --from=builder /app /app

ENV PATH=/app/bin:$PATH
