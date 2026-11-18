from station import phone


def test_kinds():
    assert phone.kind("192.168.1.20") == "network"
    assert phone.kind("192.168.1.5") == "network"
    assert phone.kind("100.64.0.10") == "tailscale"
    for ip in ("127.0.0.1", "169.254.3.4", "8.8.8.8", "fe80::1", "nonsense"):
        assert phone.kind(ip) is None


def test_addresses_order_and_dedupe():
    a = phone.addresses("192.168.1.20:8091", 8091, ips=["127.0.0.1", "192.168.1.20", "169.254.1.1", "100.64.0.10"])
    assert [x["url"] for x in a] == ["http://192.168.1.20:8091/", "http://100.64.0.10:8091/"]
    assert a[1]["label"].startswith("Tailscale")
    assert phone.addresses("localhost:8091", 8091, ips=["192.168.0.9"])[0]["url"] == "http://192.168.0.9:8091/"


def test_qr_svg():
    svg = phone.qr_svg("http://192.168.0.9:8091/")
    assert svg.startswith("<svg") and "path" in svg


def test_card_download_link_from_config():
    html = "<p><!--DOWNLOAD_QR--><!--DOWNLOAD_URL--></p>"
    out = phone.card_with_download(html, "https://example.org/get")
    assert "https://example.org/get" in out and "<svg" in out
    assert phone.REPO_URL in phone.card_with_download(html, None)           # not set: the public project page
    assert phone.REPO_URL.startswith("https://github.com/") and phone.REPO_URL.endswith("/hamsidekick")
    assert "Ask the instructor" in phone.card_with_download(html, "")       # "" = no link on the card


def test_every_card_has_a_share_qr_to_its_own_pdf_on_github():
    """Owner 2026-11-14: every reference card has a QR code back to itself on GitHub, so it can be shared fast."""
    from tools import build_ref_card
    for src, name in build_ref_card.CARDS:
        html = src.read_text(encoding="utf-8")
        assert html.count("<!--CARD_QR:") == 1 and f"<!--CARD_QR:{name}-->" in html, src.name
        out = phone.card_with_download(html, None)
        assert "CARD_QR" not in out and out.count("<svg") >= 1
        assert (build_ref_card.OUT / f"{name}.pdf").exists()
        # owner 2026-11-18: and one back to the project page, "so a new user just needs to see the QR code to get started"
        assert html.count("<!--DOWNLOAD_QR-->") == 1 and html.index("<!--DOWNLOAD_QR-->") < html.index('class="card card-back"'), src.name
        assert phone.card_with_download(html, None).count("<svg") >= 2
    assert phone.card_pdf_url("X") == phone.REPO_URL + "/blob/master/docs/X.pdf"


def test_every_card_leaves_a_binding_margin():
    """Owner 2026-11-18: about 3/4 inch on the binding edge for spiral binding (US Letter): the left of the front,
    and, printed double-sided, the right of the back."""
    from tools import build_ref_card
    for src, _ in build_ref_card.CARDS:
        css = src.read_text(encoding="utf-8")
        assert "@page{size:letter;margin:.5in .5in .5in .75in}@page :left{margin:.5in .75in .5in .5in}" in css, src.name
