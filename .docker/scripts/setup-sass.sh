#!/bin/bash

VERSION=1.89.2;

URL="https://github.com/sass/dart-sass/releases/download/${VERSION}/dart-sass-${VERSION}-linux-x64.tar.gz";

mkdir -p /opt/dart-sass;

curl -sL $URL | tar zx -C /opt;

ln -s /opt/dart-sass/sass /usr/local/bin/sass;
