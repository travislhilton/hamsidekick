"""Addresses a phone can open the dashboard at, each with a QR code (generated here, offline).

The station's firewall rule admits the PC's own subnet and Tailscale, so those are the addresses offered:
the address the browser is already using (when it is not localhost), then each private-network IPv4 of this
PC, then its Tailscale address. Link-local and loopback addresses are never offered.
"""
from __future__ import annotations

import ipaddress
import socket

TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
LABEL = {"tailscale": "Tailscale (the phone needs the Tailscale app on)", "network": "Same Wi-Fi or network as this PC"}


def kind(ip: str) -> str | None:
    """'tailscale' / 'network' for an address a phone could reach; None for loopback, link-local, public."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if a.version != 4 or a.is_loopback or a.is_link_local:
        return None
    if a in TAILSCALE:
        return "tailscale"
    return "network" if a.is_private else None


def local_ipv4() -> list[str]:
    ips: list[str] = []
    try:
        for fam, *_rest, sa in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(sa[0])
    except OSError:
        pass
    try:                                             # the address of the default route (no packet is sent)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9)); ips.append(s.getsockname()[0]); s.close()
    except OSError:
        pass
    return list(dict.fromkeys(ips))


def addresses(host_header: str | None, port: int, ips: list[str] | None = None) -> list[dict]:
    """[{url, label}] in the order a phone should try them."""
    out: list[dict] = []
    if host_header:
        h = host_header.rsplit(":", 1)[0].strip("[]")
        if h and h.lower() not in ("localhost", "127.0.0.1", "::1") and (kind(h) or not h[0].isdigit()):
            out.append({"url": f"http://{host_header}/", "label": LABEL.get(kind(h), "The address this browser is using")})
    for ip in (local_ipv4() if ips is None else ips):
        k = kind(ip)
        if k:
            out.append({"url": f"http://{ip}:{port}/", "label": LABEL[k]})
    seen, uniq = set(), []
    for a in out:
        if a["url"] not in seen:
            seen.add(a["url"]); uniq.append(a)
    return uniq


def qr_svg(text: str, error: str = "m") -> str:
    import segno
    return segno.make(text, error=error).svg_inline(scale=5, border=2, dark="#000", light="#fff", omitsize=True)


REPO_URL = "https://github.com/travislhilton/hamsidekick"   # the public project page (Code → Download ZIP)


def card_pdf_url(name: str) -> str:
    """A reference card's own PDF on GitHub (its "Share this card" QR code): GitHub's page for the file shows the PDF."""
    return f"{REPO_URL}/blob/master/docs/{name}.pdf"


def _share_qr(html: str) -> str:
    """<!--CARD_QR:<pdf name>--> -> the QR code of that card's PDF on GitHub (owner 11-14: every card has a QR code
    back to itself, so it can be shared fast)."""
    import re

    def qr(m):
        try:
            return qr_svg(card_pdf_url(m.group(1)), error="l")     # fewer, larger squares: it is printed small
        except ImportError:
            return ""
    return re.sub(r"<!--CARD_QR:(\w+)-->", qr, html)


def card_with_download(html: str, url: str | None = REPO_URL) -> str:
    """The reference card with the download link and its QR code: config/station.yaml `download_url` when set
    (a club's own copy), else the public project page. `download_url: ""` prints "ask the instructor" instead.
    Each card's "Share this card" QR code (its own PDF on GitHub) is filled in too."""
    import html as h
    html = _share_qr(html)
    if url is None:
        url = REPO_URL
    if url:
        try:
            qr = qr_svg(url)
        except ImportError:
            qr = ""
        return html.replace("<!--DOWNLOAD_QR-->", qr).replace("<!--DOWNLOAD_URL-->", h.escape(url))
    return html.replace("<!--DOWNLOAD_QR-->", "").replace(
        "<!--DOWNLOAD_URL-->", "Ask the instructor for the download link, or set download_url in config\\station.yaml")
