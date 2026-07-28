
FROM public.ecr.aws/docker/library/debian:bookworm-slim

# tell apt-get to skip interactive prompts (no human during docker build)
ENV DEBIAN_FRONTEND=noninteractive

# xvfb: virtual framebuffer (fake display rendered to memory without physical monitor)
# x11-apps: basic X11 apps for testing
# xdotool: simulate keyboard/mouse
# imagemagick: screenshots via import command (scrot doesn't work with xvfb)
# xterm: terminal emulator
# x11vnc: VNC server
# websockify + novnc: browser-based VNC client
# openbox: window manager
# chromium: real .deb on debian (ubuntu only has snap stubs that don't work in docker)
# tint2: sidebar panel with app launchers — the model's "app screen"
# dbus-x11: silences chromium's constant dbus connection errors
# the rest: everyday tools the agent needs (slim image ships without them)
RUN apt-get update && apt-get install -y \
    xvfb \
    x11-apps \
    xdotool \
    imagemagick \
    xterm \
    x11vnc \
    novnc \
    websockify \
    chromium \
    openbox \
    tint2 \
    git \
    git-lfs \
    tmux \
    curl \
    wget \
    jq \
    ripgrep \
    nano \
    vim \
    htop \
    tree \
    zip \
    unzip \
    sqlite3 \
    openssh-client \
    ca-certificates \
    dbus-x11 \
    fonts-noto-cjk \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*


# shared agent venv — baked into the image, readable by all containers.
# agents can still create their own venv under /home/agent for persistent installs.
# temporary china-friendly pip mirror.
ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
RUN python3 -m venv /opt/agent-venv && \
    /opt/agent-venv/bin/pip install --no-cache-dir \
    fastapi \
    uvicorn \
    httpx \
    websockets \
    matplotlib \
    pandas \
    ipython \
    pytest \
    huggingface_hub \
    einops \
    tqdm \
    torch
ENV PATH="/opt/agent-venv/bin:$PATH"

ENV DISPLAY=:99
# chromium runs as root in docker, needs --no-sandbox
# wrapper script so `chromium &` just works without remembering the flag
RUN echo '#!/bin/sh' > /usr/local/bin/chromium && echo 'exec /usr/bin/chromium --no-sandbox "$@"' >> /usr/local/bin/chromium && chmod +x /usr/local/bin/chromium


# tint2 sidebar: config + launcher entries (terminal respawns with the term.log logger)
COPY tint2rc /root/.config/tint2/tint2rc
COPY INT3RF4CE-terminal.desktop /usr/share/applications/INT3RF4CE-terminal.desktop
COPY INT3RF4CE-chromium.desktop /usr/share/applications/INT3RF4CE-chromium.desktop

# launcher icons: chromium glyph from its package, terminal drawn from primitives (no font needed)
RUN convert /usr/share/icons/hicolor/128x128/apps/chromium.png -resize 48x48 /usr/share/pixmaps/INT3RF4CE-chromium.png && \
    convert -size 48x48 xc:'#1a1a1a' \
        -stroke white -strokewidth 3 -fill none \
        -draw "roundrectangle 3,3 44,44 6,6" \
        -draw "polyline 14,16 22,24 14,32" \
        -stroke none -fill white \
        -draw "rectangle 26,29 36,32" \
        /usr/share/pixmaps/INT3RF4CE-terminal.png
