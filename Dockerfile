FROM ubuntu:26.04@sha256:c098726dd9b9733f3e885f8de0ef375206a311b0a317eadc40d347b1115fb944 AS toolchain

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive

RUN printf 'Acquire::Retries "8";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n' > /etc/apt/apt.conf.d/80retries

ARG UBUNTU_SNAPSHOT=20261014T000000Z
ARG PPA_POOL=https://ppa.launchpadcontent.net/dciabrin/ngdevkit/ubuntu/pool/main/n
ARG PPA_FILES=https://launchpad.net/~dciabrin/+archive/ubuntu/ngdevkit/+files
ARG NGDEVKIT_TOOLCHAIN=ngdevkit-toolchain/ngdevkit-toolchain_0.1%2b202606181616-15%7eubuntu26.04.1_amd64.deb
ARG NGDEVKIT=ngdevkit/ngdevkit_0.5%2b202610171524-17%7eubuntu26.04.1_amd64.deb
ARG NGDEVKIT_GNGEO=ngdevkit-gngeo/ngdevkit-gngeo_0.8.1%2b202607271849-11%7eubuntu26.04.1_amd64.deb

# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && apt-get update --snapshot "${UBUNTU_SNAPSHOT}" \
 && apt-get install -y --no-install-recommends --snapshot "${UBUNTU_SNAPSHOT}" \
      autoconf=2.72-3.1ubuntu2 \
      automake=1:1.18.1-3build1 \
      binutils=2.46-3ubuntu2 \
      cppcheck=2.19.0-3 \
      curl=8.18.0-1ubuntu2.7 \
      git=1:2.53.0-1ubuntu1 \
      make=4.4.1-3 \
      pkg-config=2.5.1-4 \
      python3=3.14.3-0ubuntu2 \
      rsync=3.4.1+ds1-7ubuntu0.3 \
      zip=3.0-15ubuntu3 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/ngdevkit

COPY toolchain/ngdevkit.sha256 ngdevkit.sha256

# hadolint ignore=DL3008
RUN fetch_deb() { \
      curl -fsSL --retry 5 --retry-all-errors --retry-delay 5 -o "$1" "${PPA_POOL}/$2" \
      || curl -fsSL --retry 5 --retry-all-errors --retry-delay 5 -o "$1" "${PPA_FILES}/${2#*/}"; \
    } \
 && fetch_deb ngdevkit-toolchain.deb "${NGDEVKIT_TOOLCHAIN}" \
 && fetch_deb ngdevkit.deb "${NGDEVKIT}" \
 && fetch_deb ngdevkit-gngeo.deb "${NGDEVKIT_GNGEO}" \
 && sha256sum --check --strict ngdevkit.sha256 \
 && apt-get update --snapshot "${UBUNTU_SNAPSHOT}" \
 && apt-get install -y --no-install-recommends --snapshot "${UBUNTU_SNAPSHOT}" \
      ./ngdevkit-toolchain.deb ./ngdevkit.deb ./ngdevkit-gngeo.deb \
 && rm -rf /tmp/ngdevkit/* /var/lib/apt/lists/* \
 && m68k-neogeo-elf-gcc --version | head -1

ENV NEOGEOMEDIA_IN_TOOLCHAIN_IMAGE=1

WORKDIR /work
