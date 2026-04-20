"""
PARCELA FINDER - Streamlit verzija
===================================
Pokretanje lokalno:
    pip install streamlit requests pyproj reportlab qrcode pillow
    streamlit run parcela_finder_streamlit.py

Za Streamlit Cloud - requirements.txt mora sadrzati:
    streamlit
    requests
    pyproj
    reportlab
    qrcode[pil]
    pillow
"""

import streamlit as st
import requests
import json
import re
import io
import math
from datetime import datetime
from pyproj import Transformer

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import qrcode
from PIL import Image as PILImage, ImageDraw

# ─────────────────────────────────────────────
# KONVERZIJA KOORDINATA
# ─────────────────────────────────────────────

@st.cache_resource
def get_transformer():
    return Transformer.from_crs("EPSG:32634", "EPSG:4326", always_xy=True)

def epsg_u_wgs84(x, y):
    transformer = get_transformer()
    lon, lat = transformer.transform(x, y)
    return lat, lon

def centroid_wkt(wkt):
    pts = re.findall(r'([\d.]+)\s+([\d.]+)', wkt)
    if not pts:
        return None, None
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return sum(xs)/len(xs), sum(ys)/len(ys)

def izvuci_point(wkt):
    m = re.match(r'POINT\s*\(([\d.]+)\s+([\d.]+)\)', wkt.strip())
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None

def izracunaj_povrsinu(wkt):
    pts = re.findall(r'([\d.]+)\s+([\d.]+)', wkt)
    if len(pts) < 3:
        return 0
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    n = len(xs)
    area = sum(xs[i]*ys[(i+1)%n] - xs[(i+1)%n]*ys[i] for i in range(n))
    return abs(area) / 2

# ─────────────────────────────────────────────
# API
# ─────────────────────────────────────────────

def napravi_sesiju():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
        "Accept-Language": "sr,en-US;q=0.9",
        "Referer": "https://a3.geosrbija.rs/",
        "Origin": "https://a3.geosrbija.rs",
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    })
    try:
        s.get("https://a3.geosrbija.rs/", timeout=15)
    except Exception:
        pass
    return s

def pretrazi(broj, ko, limit=50):
    s = napravi_sesiju()
    q = f"{broj} {ko.strip()}" if ko.strip() else f"{broj}*"
    payload = {
        "request": {
            "q": q,
            "srsid": "32634",
            "start": 0,
            "limit": limit,
            "layers": "507,941,948,695,694,693,589,587,586,588,939,899,1178,1177,910,49,"
                      "AdaptiveNames,AdaptiveAddresses,AdaptiveThemes",
            "bbox": {"bottom": 4750000, "left": 300000, "top": 5200000, "right": 700000}
        }
    }
    try:
        r = s.post(
            "https://a3.geosrbija.rs/WebServices/search/SearchProxy.asmx/Search",
            json=payload, timeout=15
        )
        r.raise_for_status()
        return r.json().get("d", {})
    except Exception as e:
        return {"error": str(e)}

def filtriraj(records, broj, ko):
    b = broj.strip().lower()
    k = ko.strip().lower()
    tacni = [r for r in records if (r.get("title") or "").strip().lower() == b]
    if k and tacni:
        sa_ko = [r for r in tacni if k in (r.get("desc") or "").lower()]
        if sa_ko:
            return sa_ko
    return tacni

def koordinate(rec):
    geom = rec.get("geom", "")
    full = rec.get("fullGeom", "")
    if geom.startswith("POINT"):
        x, y = izvuci_point(geom)
        if x:
            return epsg_u_wgs84(x, y)
    if full:
        x, y = centroid_wkt(full)
        if x:
            return epsg_u_wgs84(x, y)
    return None, None

# ─────────────────────────────────────────────
# GRAFIKA
# ─────────────────────────────────────────────

def nacrtaj_parcelu(full_geom, w=380, h=380, pad=35):
    pts = re.findall(r'([\d.]+)\s+([\d.]+)', full_geom)
    if not pts:
        return None
    coords = [(float(p[0]), float(p[1])) for p in pts]
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    dx = max(xs)-min(xs) or 1
    dy = max(ys)-min(ys) or 1
    skala = min((w-2*pad)/dx, (h-2*pad)/dy)

    def tp(x, y):
        return (int(pad+(x-min(xs))*skala), int(h-pad-(y-min(ys))*skala))

    img = PILImage.new("RGB", (w, h), (248, 248, 244))
    draw = ImageDraw.Draw(img)
    for i in range(0, w, 40):
        draw.line([(i, 0), (i, h)], fill=(230, 230, 225), width=1)
    for i in range(0, h, 40):
        draw.line([(0, i), (w, i)], fill=(230, 230, 225), width=1)
    shadow = [tp(x+4, y-4) for x, y in coords]
    if len(shadow) >= 3:
        draw.polygon(shadow, fill=(200, 195, 185))
    poly = [tp(x, y) for x, y in coords]
    if len(poly) >= 3:
        draw.polygon(poly, fill=(255, 235, 160))
        draw.polygon(poly, outline=(160, 100, 20), width=2)
    cx = sum(xs)/len(xs)
    cy = sum(ys)/len(ys)
    cpx, cpy = tp(cx, cy)
    draw.ellipse([cpx-6, cpy-6, cpx+6, cpy+6], fill=(200, 40, 40), outline=(150, 20, 20))
    draw.polygon([(w-22, 28), (w-29, 48), (w-22, 44)], fill=(50, 50, 50))
    draw.polygon([(w-22, 28), (w-15, 48), (w-22, 44)], fill=(180, 180, 180))
    draw.rectangle([0, 0, w-1, h-1], outline=(180, 180, 175), width=1)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf

def napravi_qr(url):
    qr = qrcode.QRCode(version=1, box_size=5, border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a3a1a", back_color="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf

def uzmi_satelit(lat, lon, zoom=18):
    lat_r = math.radians(lat)
    n = 2**zoom
    tx = int((lon + 180) / 360 * n)
    ty = int((1 - math.log(math.tan(lat_r) + 1/math.cos(lat_r)) / math.pi) / 2 * n)
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.arcgis.com/",
    })
    tile_urls = [
        f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{ty}/{tx}",
        f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
    ]
    for url in tile_urls:
        try:
            r = s.get(url, timeout=10)
            if r.status_code == 200 and len(r.content) > 500:
                img = PILImage.open(io.BytesIO(r.content)).convert("RGB")
                img = img.resize((380, 380), PILImage.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, "PNG")
                buf.seek(0)
                return buf
        except Exception:
            continue
    return None

# ─────────────────────────────────────────────
# PDF
# ─────────────────────────────────────────────

def generisi_pdf(rec, lat, lon):
    broj = rec.get("title", "")
    desc = (rec.get("desc") or "").strip()
    full_geom = rec.get("fullGeom", "")
    uid = rec.get("uid", "")
    datum = datetime.now().strftime("%d.%m.%Y u %H:%M")

    delovi = desc.split()
    n = len(delovi)
    ko_naziv = " ".join(delovi[:n//2]) if n >= 2 else desc
    opstina = " ".join(delovi[n//4:n//2]) if n >= 4 else ko_naziv

    geom_str = rec.get("geom", "")
    cx32, cy32 = None, None
    m = re.match(r'POINT\s*\(([\d.]+)\s+([\d.]+)\)', geom_str)
    if m:
        cx32, cy32 = float(m.group(1)), float(m.group(2))

    povrsina = izracunaj_povrsinu(full_geom) if full_geom else 0
    maps_url = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
    nav_url = f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}"
    waze_url = f"https://waze.com/ul?ll={lat:.6f},{lon:.6f}&navigate=yes"
    apple_url = f"https://maps.apple.com/?ll={lat:.6f},{lon:.6f}&q=Parcela+{broj.replace('/', '-')}"

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=1.8*cm, leftMargin=1.8*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
    )

    z = colors.HexColor
    s_naslov = ParagraphStyle("N", fontSize=20, fontName="Helvetica-Bold",
                               textColor=z("#1a3a1a"), alignment=TA_CENTER, spaceAfter=8)
    s_pod = ParagraphStyle("P", fontSize=10, fontName="Helvetica",
                            textColor=z("#666666"), alignment=TA_CENTER, spaceAfter=10)
    s_sek = ParagraphStyle("S", fontSize=12, fontName="Helvetica-Bold",
                            textColor=z("#2d6a4f"), spaceBefore=12, spaceAfter=5)
    s_norm = ParagraphStyle("NR", fontSize=9, fontName="Helvetica",
                             textColor=z("#333333"), leading=14)
    s_foot = ParagraphStyle("F", fontSize=7.5, fontName="Helvetica",
                             textColor=z("#999999"), alignment=TA_CENTER)

    story = []
    story.append(Paragraph("IZVOD IZ KATASTRA NEPOKRETNOSTI", s_naslov))
    story.append(Paragraph(f"Izvor: GeoSrbija (RGZ) &nbsp;|&nbsp; Generisano: {datum}", s_pod))
    story.append(HRFlowable(width="100%", thickness=2.5, color=z("#2d6a4f")))
    story.append(Spacer(1, 0.35*cm))

    story.append(Paragraph("Podaci o parceli", s_sek))
    pov_str = f"{povrsina:,.2f} m\u00b2   ({povrsina/10000:.4f} ha)"
    tabela = [
        ["Broj parcele:", broj],
        ["Katastarska opstina:", ko_naziv],
        ["Opstina:", opstina],
        ["Povrsina:", pov_str],
        ["Koordinate (WGS84):", f"lat: {lat:.6f},   lon: {lon:.6f}"],
        ["Koordinate (EPSG:32634):", f"E: {cx32:.2f},   N: {cy32:.2f}" if cx32 else "—"],
        ["Identifikator (UID):", uid],
    ]
    ts = TableStyle([
        ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
        ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 9.5),
        ("TEXTCOLOR", (0,0), (0,-1), z("#2d6a4f")),
        ("TEXTCOLOR", (1,0), (1,-1), z("#1a1a1a")),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [z("#f7f7f3"), colors.white]),
        ("GRID", (0,0), (-1,-1), 0.5, z("#dddddd")),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ])
    t = Table(tabela, colWidths=[5.2*cm, 11.2*cm])
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 0.4*cm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=z("#cccccc")))
    story.append(Paragraph("Graficki prikaz parcele", s_sek))

    parcela_buf = nacrtaj_parcelu(full_geom) if full_geom else None
    satelit_buf = uzmi_satelit(lat, lon)
    qr_buf = napravi_qr(nav_url)

    img_w = 8*cm
    img_h = 8*cm

    if parcela_buf:
        row_table = Table([[
            RLImage(parcela_buf, width=img_w, height=img_h),
            Paragraph("<font size='8' color='#666'>Oblik parcele iz katastra<br/>"
                      "Zuta boja = povrsina parcele<br/>"
                      "Crvena tacka = centroid<br/>"
                      "N strelica = sever</font>", s_norm)
        ]], colWidths=[img_w + 0.3*cm, 7.5*cm])
        row_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 4),
        ]))
        story.append(row_table)
        story.append(Spacer(1, 0.2*cm))

    if satelit_buf:
        row_table2 = Table([[
            RLImage(satelit_buf, width=img_w, height=img_h),
            Paragraph("<font size='8' color='#666'>Satelitski snimak lokacije<br/>"
                      "(ArcGIS World Imagery)</font>", s_norm)
        ]], colWidths=[img_w + 0.3*cm, 7.5*cm])
        row_table2.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 4),
        ]))
        story.append(row_table2)
        story.append(Spacer(1, 0.2*cm))

    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=z("#cccccc")))
    story.append(Paragraph("Navigacija do parcele", s_sek))

    def link_para(url):
        return Paragraph(f'<link href="{url}"><font color="#1a5fa8" size="8.5">{url}</font></link>', s_norm)

    nav_tabela = [
        [Paragraph("<b>Google Maps (prikaz):</b>", ParagraphStyle("lb", fontSize=8.5, fontName="Helvetica-Bold", textColor=z("#2d6a4f"), leading=13)), link_para(maps_url)],
        [Paragraph("<b>Google Maps (navigacija):</b>", ParagraphStyle("lb2", fontSize=8.5, fontName="Helvetica-Bold", textColor=z("#2d6a4f"), leading=13)), link_para(nav_url)],
        [Paragraph("<b>Waze:</b>", ParagraphStyle("lb3", fontSize=8.5, fontName="Helvetica-Bold", textColor=z("#2d6a4f"), leading=13)), link_para(waze_url)],
        [Paragraph("<b>Apple Maps:</b>", ParagraphStyle("lb4", fontSize=8.5, fontName="Helvetica-Bold", textColor=z("#2d6a4f"), leading=13)), link_para(apple_url)],
    ]
    t_nav = Table(nav_tabela, colWidths=[5.2*cm, 9.8*cm])
    t_nav.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), 8.5),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [z("#f7f7f3"), colors.white]),
        ("GRID", (0,0), (-1,-1), 0.5, z("#dddddd")),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))

    qr_img = RLImage(qr_buf, width=3.5*cm, height=3.5*cm)
    qr_label = Paragraph("<font size='7.5' color='#555'>Skeniraj QR kod<br/>za navigaciju</font>", s_norm)
    qr_cell = Table([[qr_img], [qr_label]], colWidths=[4*cm])
    qr_cell.setStyle(TableStyle([("ALIGN", (0,0), (-1,-1), "CENTER"),
                                  ("VALIGN", (0,0), (-1,-1), "MIDDLE")]))
    nav_row = Table([[t_nav, qr_cell]], colWidths=[15*cm, 4*cm])
    nav_row.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (1,0), (1,0), 10),
    ]))
    story.append(nav_row)
    story.append(Spacer(1, 0.5*cm))

    story.append(HRFlowable(width="100%", thickness=1.5, color=z("#2d6a4f")))
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        "Ovaj dokument je generisan automatski na osnovu javno dostupnih podataka GeoSrbija portala (RGZ). "
        "Nije zvanicni izvod iz katastra i ne moze se koristiti u pravne svrhe. "
        f"Za zvanicni izvod obratite se Republickom geodetskom zavodu. | {datum}",
        s_foot
    ))

    doc.build(story)
    buf.seek(0)
    return buf

# ─────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Parcela Finder",
    page_icon="🗺️",
    layout="centered"
)

st.markdown("""
<style>
    .main-title { font-size: 2rem; font-weight: 700; color: #1a3a1a; }
    .sub-title { color: #666; margin-bottom: 1.5rem; }
    .result-box {
        background: #f7f7f3;
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin: 0.5rem 0;
    }
    .coord-text { font-family: monospace; font-size: 0.95rem; color: #333; }
    .povrsina { font-size: 1.1rem; font-weight: 600; color: #2d6a4f; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🗺️ Parcela Finder</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Pronađi parcelu → Google Maps + PDF izveštaj</div>', unsafe_allow_html=True)

# Forma za pretragu
with st.container():
    col1, col2 = st.columns([1, 1])
    with col1:
        broj = st.text_input("Broj parcele", value="11585", placeholder="npr. 11585")
    with col2:
        ko = st.text_input("Katastarska opština (deo naziva)", value="Zemun", placeholder="npr. Zemun")

    trazi = st.button("🔍 Pronađi parcelu", type="primary", use_container_width=True)

# Pretraga
if trazi:
    if not broj.strip():
        st.error("Unesite broj parcele.")
    else:
        with st.spinner("Pretražujem GeoSrbija..."):
            odg = pretrazi(broj.strip(), ko.strip())

        if "error" in odg:
            st.error(f"Greška pri pretrazi: {odg['error']}")
        else:
            recs = odg.get("records", [])
            if not recs:
                st.warning("Nema rezultata za zadatu pretragu.")
            else:
                fil = filtriraj(recs, broj.strip(), ko.strip())
                if not fil:
                    st.warning(f"Nije pronađena parcela '{broj}' u '{ko}'. Proverite unos.")
                else:
                    st.session_state["rezultati"] = fil
                    st.session_state["odabrani"] = 0 if len(fil) == 1 else None

# Prikaz rezultata
if "rezultati" in st.session_state and st.session_state["rezultati"]:
    rezultati = st.session_state["rezultati"]

    if len(rezultati) > 1:
        opcije = [f"{r.get('title','')}  —  {(r.get('desc') or '').replace('  ', ' ')}" for r in rezultati]
        odabran_idx = st.selectbox("Pronađeno više parcela — odaberite jednu:", range(len(opcije)),
                                    format_func=lambda i: opcije[i])
        st.session_state["odabrani"] = odabran_idx
    
    odabrani_idx = st.session_state.get("odabrani", 0)
    if odabrani_idx is not None:
        rec = rezultati[odabrani_idx]
        lat, lon = koordinate(rec)

        if lat is None:
            st.error("Nema koordinata za ovu parcelu.")
        else:
            pov = izracunaj_povrsinu(rec.get("fullGeom", ""))
            desc = (rec.get("desc") or "").replace("  ", " ")

            st.success("✅ Parcela pronađena!")

            st.markdown(f"""
            <div class="result-box">
                <div class="coord-text">lat: {lat:.6f} &nbsp;&nbsp; lon: {lon:.6f}</div>
                <div class="povrsina">Površina: {pov:,.2f} m² &nbsp; ({pov/10000:.4f} ha)</div>
                <div style="color:#666; font-size:0.9rem; margin-top:4px">{desc}</div>
            </div>
            """, unsafe_allow_html=True)

            # Mapa
            st.map(data={"lat": [lat], "lon": [lon]}, zoom=15)

            # Linkovi za navigaciju
            st.markdown("### 🧭 Navigacija")
            c1, c2, c3 = st.columns(3)
            maps_url = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
            nav_url = f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}"
            waze_url = f"https://waze.com/ul?ll={lat:.6f},{lon:.6f}&navigate=yes"

            c1.link_button("🗺️ Google Maps", maps_url, use_container_width=True)
            c2.link_button("🚗 Navigacija", nav_url, use_container_width=True)
            c3.link_button("🔵 Waze", waze_url, use_container_width=True)

            # Prikaz oblika parcele
            full_geom = rec.get("fullGeom", "")
            if full_geom:
                parcela_buf = nacrtaj_parcelu(full_geom)
                if parcela_buf:
                    st.markdown("### 📐 Oblik parcele")
                    st.image(parcela_buf, caption="Oblik parcele iz katastra (žuta = površina, crvena tačka = centroid)", width=300)

            # PDF dugme
            st.markdown("### 📄 PDF Izveštaj")
            if st.button("📥 Generiši PDF izveštaj", use_container_width=True):
                with st.spinner("Generišem PDF... (može trajati ~10 sekundi)"):
                    try:
                        pdf_buf = generisi_pdf(rec, lat, lon)
                        broj_naziv = rec.get("title", "parcela").replace("/", "-")
                        ko_naziv = desc.split()[0] if desc else "KO"
                        ime = f"Parcela_{broj_naziv}_{ko_naziv}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                        st.download_button(
                            label="💾 Preuzmi PDF",
                            data=pdf_buf,
                            file_name=ime,
                            mime="application/pdf",
                            use_container_width=True
                        )
                        st.success("PDF uspešno generisan! Kliknite 'Preuzmi PDF' iznad.")
                    except Exception as e:
                        st.error(f"Greška pri generisanju PDF-a: {e}")

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align:center; color:#aaa; font-size:0.8rem'>"
    "Podaci su preuzeti sa GeoSrbija (RGZ) · Nije zvanični izvod iz katastra"
    "</div>",
    unsafe_allow_html=True
)
