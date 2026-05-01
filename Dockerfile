# =============================================================================
# Legion — Production Docker Image
# =============================================================================
# Runs Legion in --web mode.  Exposes port 5000.
#
# IMPORTANT: Build from the flask-clean branch (not master):
#   git clone --branch flask-clean <repo-url>
#   cd legion
#   sudo docker build -t legion .
#
# If you already cloned: git checkout flask-clean
#
# Quick start:
#   sudo docker build -t legion .
#   sudo docker run -d --name legion \
#     --network host \
#     --cap-add NET_ADMIN --cap-add NET_RAW \
#     -v legion-projects:/root/.local/share/legion \
#     legion
#   # Open http://127.0.0.1:5000 in your browser
#
# See INSTALL.md for full options and docker-compose instructions.
# =============================================================================

FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

# ── Base packages ─────────────────────────────────────────────────────────────
RUN apt-get update -q && apt-get install -y \
    python3 python3-pip python3-dev \
    git build-essential curl wget ca-certificates golang-go \
    libssl3 openssl libgl1 libegl1 \
    libglib2.0-0 libdbus-1-3 libfontconfig1 libfreetype6 \
    libx11-6 libxext6 libxrender1 libxcb1 libxkbcommon0 \
    xvfb firefox-esr \
    nmap masscan hping3 ike-scan \
    feroxbuster gobuster ffuf nikto whatweb wafw00f \
    wpscan joomscan davtest sqlmap sslyze sslscan testssl \
    dnsrecon dnsenum nbtscan onesixtyone snmpwalk snmpcheck \
    rpcinfo nfs-common ldap-utils \
    netexec smbmap enum4linux-ng ldapdomaindump smbclient \
    impacket-scripts hydra eyewitness \
    exploitdb ssh-audit \
    redis-tools swaks smtp-user-enum finger \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── geckodriver ───────────────────────────────────────────────────────────────
RUN curl -fsSL "https://github.com/mozilla/geckodriver/releases/download/v0.35.0/geckodriver-v0.35.0-linux64.tar.gz" \
    | tar xz -C /usr/local/bin && chmod +x /usr/local/bin/geckodriver

# ── Go-based tools ────────────────────────────────────────────────────────────
RUN for pkg_dest in \
    "github.com/projectdiscovery/httpx/cmd/httpx@latest:pd-httpx" \
    "github.com/projectdiscovery/katana/cmd/katana@latest:katana" \
    "github.com/lc/gau/v2/cmd/gau@latest:gau" \
    "github.com/tomnomnom/waybackurls@latest:waybackurls" \
    "github.com/devploit/nomore403@latest:nomore403" \
    "github.com/projectdiscovery/urlfinder/cmd/urlfinder@latest:urlfinder" \
; do \
    pkg="${pkg_dest%%:*}"; dest="${pkg_dest##*:}"; \
    tmpdir=$(mktemp -d); \
    GOPATH=$tmpdir HOME=/root go install "$pkg" 2>/dev/null && \
        (find "$tmpdir/bin" -type f -exec cp {} /usr/local/bin/"$dest" \; 2>/dev/null || true); \
    rm -rf "$tmpdir"; \
done

# ── /opt tools ────────────────────────────────────────────────────────────────
RUN git clone --depth 1 https://github.com/joaomatosf/jexboss.git /opt/jexboss 2>/dev/null && \
    pip3 install --break-system-packages -r /opt/jexboss/requires.txt -q 2>/dev/null || true

RUN git clone --depth 1 https://github.com/JoelGMSec/LeakSearch.git /opt/LeakSearch 2>/dev/null && \
    pip3 install --break-system-packages neotermcolor -q

# ── Copy Legion ───────────────────────────────────────────────────────────────
WORKDIR /legion
COPY . .

# ── Python packages ───────────────────────────────────────────────────────────
RUN pip3 install --break-system-packages -q -r requirements.txt

# ── Runtime setup ─────────────────────────────────────────────────────────────
RUN mkdir -p /tmp/legion /root/.local/share/legion/autosave \
             /root/.mozilla/firefox/legion-profile /projects

VOLUME ["/root/.local/share/legion", "/tmp/legion", "/projects"]
EXPOSE 5000

# Xvfb display for eyewitness screenshooter, then start Legion
ENTRYPOINT ["/bin/bash", "-c", \
    "Xvfb :99 -screen 0 1280x1024x24 -ac &>/dev/null & \
     exec python3 legion.py --web --no-browser \"$@\"", "--"]
CMD ["--port", "5000"]
