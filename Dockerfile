FROM python:3.13-trixie as build
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
RUN <<EOT
apt update && apt install xmlsec1 -y
EOT

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.13 \
    UV_PROJECT_ENVIRONMENT=/app

RUN --mount=type=cache,target=/root/.cache \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync \
        --locked \
        --no-dev \
        --no-install-project

##### Production image
FROM python:3.13-trixie
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PATH=/app/bin:$PATH
# Don't run your app as root.
RUN <<EOT
groupadd -r app
useradd -r -d /app -g app -N app
EOT

RUN <<EOT
apt-get clean
apt update && apt install xmlsec1 curl locales -y
apt dist-upgrade -y

# Generate a UTF-8 locale so the `locale` command and Python report en_US.UTF-8.
sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
locale-gen

# dart-sass is invoked by docker-entrypoint.sh to build the stylesheets.
SASS_VERSION=1.89.2
curl -sL "https://github.com/sass/dart-sass/releases/download/${SASS_VERSION}/dart-sass-${SASS_VERSION}-linux-x64.tar.gz" | tar zx -C /opt
ln -s /opt/dart-sass/sass /usr/local/bin/sass

rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
EOT
ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8
# Copy from the build container
COPY --from=build --chown=app:app /app /app
COPY --chown=app:app ./hittade /app/hittade
COPY --chown=app:app ./api /app/api
COPY --chown=app:app ./servers /app/servers
COPY --chown=app:app ./containers /app/containers
COPY --chown=app:app ./start_page /app/start_page
COPY --chown=app:app ./attributemaps /app/attributemaps
COPY --chown=app:app ./templates /app/templates
COPY --chown=app:app ./static /app/static
COPY --chown=app:app ./scripts /app/scripts
COPY --chown=app:app ./docker-entrypoint.sh /app/
COPY --chown=app:app ./manage.py /app/

USER app
WORKDIR /app
