# Reproducible dev environment for microweaver-framework.
# Builds the CPython 3.11 toolchain the test suite and tinker.py need
# (poetry, mpy-cross-multi, esptool, pyserial) — not a runtime image,
# since app/config/boot.py/main.py only ever run on-device under MicroPython.
FROM python:3.11-slim

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir poetry

WORKDIR /workspace

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root

COPY . .

CMD ["bash"]
