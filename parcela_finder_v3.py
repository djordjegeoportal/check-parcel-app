"""
PARCELA FINDER v3 - SA PDF IZVESTAJEM
======================================
Instalacija:
    pip install requests pyproj reportlab qrcode pillow

Pokretanje:
    python parcela_finder_v3.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import requests
import webbrowser
import threading
import json
import re
import os
import io
import math
import tempfile
from datetime import datetime
from pyproj import Transformer

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import qrcode
from PIL import Image as PILImage, ImageDraw, ImageFont

# ─────────────────────────────────────────────
# KONVERZIJA KOORDINATA
# ─────────────────────────────────────────────

transformer = Transformer.from_crs("EPSG:32634", "EPSG:4326", always_xy=True)

def epsg_u_wgs84(x, y):
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

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept-Language": "sr,en-US;q=0.9",
    "Referer": "https://a3.geosrbija.rs/",
    "Origin": "https://a3.geosrbija.rs",
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
})

_sesija_ok = False

def inicijalizuj():
    global _sesija_ok
    if _sesija_ok:
        return
    try:
        SESSION.get("https://a3.geosrbija.rs/", timeout=15)
        _sesija_ok = True
    except Exception:
        pass

def pretrazi(broj, ko, limit=50):
    # Uključi KO u upit da API odmah filtrira, umesto da vraća 200 nepovezanih rezultata
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
        r = SESSION.post(
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
    # Filtriraj po tacnom broju parcele
    tacni = [r for r in records if (r.get("title") or "").strip().lower() == b]
    # Ako je KO uneto, pokusaj da filtriras i po njemu
    if k and tacni:
        sa_ko = [r for r in tacni if k in (r.get("desc") or "").lower()]
        if sa_ko:
            return sa_ko
    # Vrati sve sa tacnim brojem ako KO filter nije dao rezultate
    return tacni

def koordinate(rec):
    geom = rec.get("geom", "")
    full = rec.get("fullGeom", "")
    if geom.startswith("POINT"):
        x, y = izvuci_point(geom)
        if x: return epsg_u_wgs84(x, y)
    if full:
        x, y = centroid_wkt(full)
        if x: return epsg_u_wgs84(x, y)
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

    # mreža
    for i in range(0, w, 40):
        draw.line([(i, 0), (i, h)], fill=(230, 230, 225), width=1)
    for i in range(0, h, 40):
        draw.line([(0, i), (w, i)], fill=(230, 230, 225), width=1)

    # senka
    shadow = [tp(x+4, y-4) for x, y in coords]
    if len(shadow) >= 3:
        draw.polygon(shadow, fill=(200, 195, 185))

    # parcela
    poly = [tp(x, y) for x, y in coords]
    if len(poly) >= 3:
        draw.polygon(poly, fill=(255, 235, 160))
        draw.polygon(poly, outline=(160, 100, 20), width=2)
        draw.polygon(poly, outline=(120, 70, 10), width=1)

    # centroid
    cx = sum(xs)/len(xs)
    cy = sum(ys)/len(ys)
    cpx, cpy = tp(cx, cy)
    draw.ellipse([cpx-6, cpy-6, cpx+6, cpy+6], fill=(200, 40, 40), outline=(150, 20, 20))

    # sever
    draw.polygon([(w-22, 28), (w-29, 48), (w-22, 44)], fill=(50, 50, 50))
    draw.polygon([(w-22, 28), (w-15, 48), (w-22, 44)], fill=(180, 180, 180))
    draw.ellipse([w-26, 48, w-18, 56], outline=(50,50,50), width=1)

    # okvir
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
    """Preuzima satelitski snimak lokacije parcele."""
    lat_r = math.radians(lat)
    n = 2**zoom
    tx = int((lon + 180) / 360 * n)
    ty = int((1 - math.log(math.tan(lat_r) + 1/math.cos(lat_r)) / math.pi) / 2 * n)

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Referer": "https://www.arcgis.com/",
    })

    tile_urls = [
        # ArcGIS satelitski snimak (prioritet)
        f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{ty}/{tx}",
        f"https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{zoom}/{ty}/{tx}",
        # Fallback na OSM
        f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
        f"https://a.tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
        f"https://b.tile.openstreetmap.org/{zoom}/{tx}/{ty}.png",
    ]

    for url in tile_urls:
        try:
            r = s.get(url, timeout=10)
            ct = r.headers.get("Content-Type", "")
            if r.status_code == 200 and ("image" in ct or len(r.content) > 500):
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

def generiši_pdf(rec, lat, lon, putanja):
    broj      = rec.get("title", "")
    desc      = (rec.get("desc") or "").strip()
    full_geom = rec.get("fullGeom", "")
    uid       = rec.get("uid", "")
    datum     = datetime.now().strftime("%d.%m.%Y u %H:%M")

    # Parsiranje opisa "MESTO OPST МЕСТО ОПШТИНИ"
    delovi = desc.split()
    n = len(delovi)
    ko_naziv = " ".join(delovi[:n//2]) if n >= 2 else desc
    opstina  = " ".join(delovi[n//4:n//2]) if n >= 4 else ko_naziv

    # Koordinate u 32634
    geom_str = rec.get("geom", "")
    cx32, cy32 = None, None
    m = re.match(r'POINT\s*\(([\d.]+)\s+([\d.]+)\)', geom_str)
    if m:
        cx32, cy32 = float(m.group(1)), float(m.group(2))

    povrsina = izracunaj_povrsinu(full_geom) if full_geom else 0
    maps_url  = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
    nav_url   = f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}"
    waze_url  = f"https://waze.com/ul?ll={lat:.6f},{lon:.6f}&navigate=yes"
    apple_url = f"https://maps.apple.com/?ll={lat:.6f},{lon:.6f}&q=Parcela+{broj.replace('/', '-')}"

    doc = SimpleDocTemplate(
        putanja, pagesize=A4,
        rightMargin=1.8*cm, leftMargin=1.8*cm,
        topMargin=1.8*cm, bottomMargin=1.8*cm,
        title=f"Izvestaj parcela {broj} - {ko_naziv}",
    )

    styles = getSampleStyleSheet()
    z = colors.HexColor

    s_naslov = ParagraphStyle("N", fontSize=20, fontName="Helvetica-Bold",
                               textColor=z("#1a3a1a"), alignment=TA_CENTER, spaceAfter=8)
    s_pod    = ParagraphStyle("P", fontSize=10, fontName="Helvetica",
                               textColor=z("#666666"), alignment=TA_CENTER, spaceAfter=10)
    s_sek    = ParagraphStyle("S", fontSize=12, fontName="Helvetica-Bold",
                               textColor=z("#2d6a4f"), spaceBefore=12, spaceAfter=5)
    s_norm   = ParagraphStyle("NR", fontSize=9, fontName="Helvetica",
                               textColor=z("#333333"), leading=14)
    s_foot   = ParagraphStyle("F", fontSize=7.5, fontName="Helvetica",
                               textColor=z("#999999"), alignment=TA_CENTER)
    s_link   = ParagraphStyle("L", fontSize=8.5, fontName="Helvetica",
                               textColor=z("#1a5fa8"), leading=13)

    story = []

    # Zaglavlje
    story.append(Paragraph("IZVOD IZ KATASTRA NEPOKRETNOSTI", s_naslov))
    story.append(Paragraph(f"Izvor: GeoSrbija (RGZ) &nbsp;|&nbsp; Generisano: {datum}", s_pod))
    story.append(HRFlowable(width="100%", thickness=2.5, color=z("#2d6a4f")))
    story.append(Spacer(1, 0.35*cm))

    # Podaci o parceli
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
        ("FONTNAME",    (0,0), (-1,-1), "Helvetica"),
        ("FONTNAME",    (0,0), (0,-1),  "Helvetica-Bold"),
        ("FONTSIZE",    (0,0), (-1,-1), 9.5),
        ("TEXTCOLOR",   (0,0), (0,-1),  z("#2d6a4f")),
        ("TEXTCOLOR",   (1,0), (1,-1),  z("#1a1a1a")),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [z("#f7f7f3"), colors.white]),
        ("GRID",        (0,0), (-1,-1), 0.5, z("#dddddd")),
        ("TOPPADDING",  (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
    ])
    t = Table(tabela, colWidths=[5.2*cm, 11.2*cm])
    t.setStyle(ts)
    story.append(t)
    story.append(Spacer(1, 0.4*cm))

    # Graficki prikaz
    story.append(HRFlowable(width="100%", thickness=0.5, color=z("#cccccc")))
    story.append(Paragraph("Graficki prikaz parcele", s_sek))

    parcela_buf = nacrtaj_parcelu(full_geom) if full_geom else None
    satelit_buf = uzmi_satelit(lat, lon)
    qr_buf      = napravi_qr(nav_url)

    img_w = 8*cm
    img_h = 8*cm

    # Red sa slikama
    img_cells = []

    if parcela_buf:
        img_cells.append([
            Image(parcela_buf, width=img_w, height=img_h),
            Paragraph("<font size='8' color='#666'>Oblik parcele iz katastra<br/>"
                      "Zuta boja = povrsina parcele<br/>"
                      "Crvena tacka = centroid<br/>"
                      "N strelica = sever</font>", s_norm)
        ])

    if satelit_buf:
        img_cells.append([
            Image(satelit_buf, width=img_w, height=img_h),
            Paragraph("<font size='8' color='#666'>Satelitski snimak lokacije<br/>"
                      "(ArcGIS World Imagery)</font>", s_norm)
        ])

    if img_cells:
        # Prikazi sve slike u redu
        for img_cell in img_cells:
            row_table = Table([img_cell], colWidths=[img_w + 0.3*cm, 7.5*cm])
            row_table.setStyle(TableStyle([
                ("VALIGN", (0,0), (-1,-1), "TOP"),
                ("LEFTPADDING", (0,0), (-1,-1), 4),
                ("RIGHTPADDING", (0,0), (-1,-1), 4),
                ("TOPPADDING", (0,0), (-1,-1), 0),
            ]))
            story.append(row_table)
            story.append(Spacer(1, 0.2*cm))

    story.append(Spacer(1, 0.3*cm))

    # QR i linkovi
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
        ("FONTNAME",    (0,0), (-1,-1), "Helvetica"),
        ("FONTSIZE",    (0,0), (-1,-1), 8.5),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [z("#f7f7f3"), colors.white]),
        ("GRID",        (0,0), (-1,-1), 0.5, z("#dddddd")),
        ("TOPPADDING",  (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
    ]))

    # QR kod ispod tabele, centriran
    qr_img = Image(qr_buf, width=3.5*cm, height=3.5*cm)
    qr_label = Paragraph("<font size='7.5' color='#555'>Skeniraj QR kod<br/>za navigaciju</font>", s_norm)
    qr_cell = Table([[qr_img], [qr_label]], colWidths=[4*cm])
    qr_cell.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),
                                  ("VALIGN",(0,0),(-1,-1),"MIDDLE")]))

    nav_row = Table([[t_nav, qr_cell]], colWidths=[15*cm, 4*cm])
    nav_row.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (1,0), (1,0), 10),
    ]))
    story.append(nav_row)
    story.append(Spacer(1, 0.5*cm))

    # Footer
    story.append(HRFlowable(width="100%", thickness=1.5, color=z("#2d6a4f")))
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        "Ovaj dokument je generisan automatski na osnovu javno dostupnih podataka GeoSrbija portala (RGZ). "
        "Nije zvanicni izvod iz katastra i ne moze se koristiti u pravne svrhe. "
        f"Za zvanicni izvod obratite se Republickom geodetskom zavodu. | {datum}",
        s_foot
    ))

    doc.build(story)


# ─────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────

class ParcelaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Parcela Finder v3")
        self.root.geometry("580x740")
        self.root.resizable(True, True)
        self.root.configure(bg="#f4f4f0")
        self.rezultati = []
        self.odabrani_rec = None
        self.lat = self.lon = None
        self._gui()

    def _gui(self):
        bg = "#f4f4f0"; cb = "#ffffff"; z = "#2d6a4f"

        tk.Label(self.root, text="Parcela Finder", font=("Segoe UI",20,"bold"),
                 bg=bg, fg="#1a1a1a").pack(pady=(18,2))
        tk.Label(self.root, text="Pronadi parcelu  →  Google Maps  +  PDF izvestaj",
                 font=("Segoe UI",10), bg=bg, fg="#666").pack(pady=(0,12))

        card = tk.Frame(self.root, bg=cb, highlightbackground="#ddd", highlightthickness=1)
        card.pack(padx=20, fill="x")

        def lbl(p, t):
            tk.Label(p, text=t, font=("Segoe UI",10), bg=cb, fg="#444", anchor="w").pack(
                fill="x", padx=18, pady=(10,2))

        lbl(card, "Broj parcele")
        self.e_broj = ttk.Entry(card, font=("Segoe UI",12))
        self.e_broj.pack(fill="x", padx=18, pady=(0,4))
        self.e_broj.insert(0, "11585")
        self.e_broj.bind("<Return>", lambda e: self._trazi())

        lbl(card, "Katastarska opstina (deo naziva)")
        self.e_ko = ttk.Entry(card, font=("Segoe UI",12))
        self.e_ko.pack(fill="x", padx=18, pady=(0,4))
        self.e_ko.insert(0, "Zemun")
        self.e_ko.bind("<Return>", lambda e: self._trazi())

        tk.Frame(card, bg="#ececec", height=1).pack(fill="x", padx=18, pady=10)
        self.btn_trazi = tk.Button(card, text="Pronadi parcelu  →",
            font=("Segoe UI",12,"bold"), bg=z, fg="white",
            activebackground="#1b4332", relief="flat", cursor="hand2",
            pady=10, command=self._trazi)
        self.btn_trazi.pack(fill="x", padx=18, pady=(0,18))

        self.lbl_st = tk.Label(self.root, text="", font=("Segoe UI",10),
                                bg=bg, fg="#888", wraplength=520)
        self.lbl_st.pack(pady=5)
        self.prog = ttk.Progressbar(self.root, mode="indeterminate", length=320)

        # Lista
        self.frm_lista = tk.Frame(self.root, bg=bg)
        tk.Label(self.frm_lista, text="Pronadene parcele:", font=("Segoe UI",10),
                 bg=bg, fg="#555").pack(anchor="w", padx=20)
        lbf = tk.Frame(self.frm_lista, bg=bg)
        lbf.pack(fill="x", padx=20, pady=3)
        sb = tk.Scrollbar(lbf)
        sb.pack(side="right", fill="y")
        self.lb = tk.Listbox(lbf, font=("Segoe UI",10), height=5,
                              selectbackground=z, selectforeground="white",
                              yscrollcommand=sb.set, relief="flat",
                              highlightbackground="#ddd", highlightthickness=1)
        self.lb.pack(fill="x", side="left", expand=True)
        sb.config(command=self.lb.yview)
        self.lb.bind("<<ListboxSelect>>", self._odabir)

        # Rezultat
        self.frm_res = tk.Frame(self.root, bg=cb,
                                 highlightbackground="#ddd", highlightthickness=1)
        tk.Label(self.frm_res, text="Parcela pronadena", font=("Segoe UI",11,"bold"),
                 bg=cb, fg=z).pack(pady=(14,4))
        self.lbl_c  = tk.Label(self.frm_res, text="", font=("Courier New",10),
                                bg=cb, fg="#333")
        self.lbl_c.pack()
        self.lbl_pov = tk.Label(self.frm_res, text="", font=("Segoe UI",11,"bold"),
                                 bg=cb, fg=z)
        self.lbl_pov.pack(pady=(2,0))
        self.lbl_d  = tk.Label(self.frm_res, text="", font=("Segoe UI",10),
                                bg=cb, fg="#666")
        self.lbl_d.pack(pady=(2,8))
        tk.Frame(self.frm_res, bg="#ececec", height=1).pack(fill="x", padx=18)

        nbf = tk.Frame(self.frm_res, bg=cb)
        nbf.pack(pady=8, padx=18)
        def nbtn(t, c, tip):
            return tk.Button(nbf, text=t, font=("Segoe UI",10,"bold"), bg=c,
                             fg="white", relief="flat", cursor="hand2", padx=10, pady=7,
                             command=lambda: self._otvori(tip))
        nbtn("Google Maps", "#4285F4", "pin").grid(row=0, column=0, padx=3)
        nbtn("Navigacija",  "#34A853", "nav").grid(row=0, column=1, padx=3)
        nbtn("Waze",        "#05C8F7", "waze").grid(row=0, column=2, padx=3)

        tk.Frame(self.frm_res, bg="#ececec", height=1).pack(fill="x", padx=18, pady=6)
        self.btn_pdf = tk.Button(self.frm_res,
            text="Generisi PDF izvestaj",
            font=("Segoe UI",11,"bold"), bg="#8B4513", fg="white",
            activebackground="#6B3410", relief="flat", cursor="hand2",
            pady=9, command=self._pdf)
        self.btn_pdf.pack(fill="x", padx=18, pady=(0,16))

        dbf = tk.Frame(self.root, bg=bg)
        dbf.pack(fill="x", padx=20, pady=(6,4))
        tk.Label(dbf, text="Dijagnostika:", font=("Segoe UI",9), bg=bg, fg="#bbb").pack(anchor="w")
        self.dbg = tk.Text(dbf, height=4, font=("Courier New",8),
                           bg="#efefef", fg="#777", relief="flat",
                           highlightbackground="#ddd", highlightthickness=1)
        self.dbg.pack(fill="x")

    def _st(self, msg, c="#666"):
        self.lbl_st.config(text=msg, fg=c)
        self.root.update_idletasks()

    def _dbg(self, d):
        self.dbg.delete("1.0", tk.END)
        self.dbg.insert("1.0", (json.dumps(d, indent=2, ensure_ascii=False)
                                if isinstance(d,(dict,list)) else str(d))[:3000])

    def _trazi(self):
        self.btn_trazi.config(state="disabled")
        self.frm_lista.pack_forget()
        self.frm_res.pack_forget()
        self.lb.delete(0, tk.END)
        self.rezultati = []
        self.odabrani_rec = None
        self.prog.pack(pady=4)
        self.prog.start(10)
        threading.Thread(target=self._thread, daemon=True).start()

    def _thread(self):
        try:
            broj = self.e_broj.get().strip()
            ko   = self.e_ko.get().strip()
            if not broj:
                self._st("Unesi broj parcele.", "#c0392b"); return
            self._st("Uspostavljam konekciju...")
            inicijalizuj()
            self._st(f"Pretrazujem '{broj}'...")
            odg = pretrazi(broj, ko)
            if "error" in odg:
                self._st(f"Greska: {odg['error']}", "#c0392b")
                self._dbg(odg); return
            recs = odg.get("records", [])
            self._dbg({"ukupno": len(recs), "prvih3": recs[:3]})
            if not recs:
                self._st("Nema rezultata.", "#c0392b"); return
            fil = filtriraj(recs, broj, ko)
            if not fil:
                self._st(f"Nije pronadjena parcela '{broj}' u '{ko}'.", "#c0392b"); return
            self.rezultati = fil
            self.root.after(0, self._lista)
        except Exception as e:
            import traceback
            self._st(f"Greska: {e}", "#c0392b")
            self._dbg(traceback.format_exc())
        finally:
            self.root.after(0, self._kraj)

    def _kraj(self):
        self.prog.stop(); self.prog.pack_forget()
        self.btn_trazi.config(state="normal")

    def _lista(self):
        self.lb.delete(0, tk.END)
        for r in self.rezultati:
            self.lb.insert(tk.END, f"  {r.get('title','')}  —  {(r.get('desc') or '').replace('  ',' ')}")
        n = len(self.rezultati)
        if n == 1:
            self.lb.selection_set(0)
            self._odabir(None)
            self._st("Pronadjena 1 parcela.", "#27ae60")
        else:
            self._st(f"Pronadjeno {n} parcela. Odaberi jednu.", "#2980b9")
        self.frm_lista.pack(padx=20, fill="x", pady=4)

    def _odabir(self, _):
        sel = self.lb.curselection()
        if not sel: return
        rec = self.rezultati[sel[0]]
        self.odabrani_rec = rec
        lat, lon = koordinate(rec)
        if lat is None:
            self._st("Nema koordinata.", "#c0392b"); return
        self.lat, self.lon = lat, lon
        pov = izracunaj_povrsinu(rec.get("fullGeom",""))
        self.lbl_c.config(text=f"lat: {lat:.6f}   lon: {lon:.6f}")
        self.lbl_pov.config(text=f"Povrsina: {pov:,.2f} m\u00b2  ({pov/10000:.4f} ha)")
        self.lbl_d.config(text=(rec.get("desc") or "").replace("  "," "))
        self._dbg(rec)
        self.frm_res.pack(padx=20, fill="x", pady=6)
        self._st("Klikni dugme za navigaciju ili generiši PDF.", "#27ae60")

    def _otvori(self, tip):
        if self.lat is None: return
        urls = {
            "pin":  f"https://www.google.com/maps?q={self.lat},{self.lon}",
            "nav":  f"https://www.google.com/maps/dir/?api=1&destination={self.lat},{self.lon}",
            "waze": f"https://waze.com/ul?ll={self.lat},{self.lon}&navigate=yes",
        }
        webbrowser.open(urls[tip])

    def _pdf(self):
        if not self.odabrani_rec or self.lat is None:
            messagebox.showwarning("Upozorenje", "Najpre odaberi parcelu.")
            return
        broj = self.odabrani_rec.get("title","parcela")
        ko   = (self.odabrani_rec.get("desc") or "KO").split()[0]
        broj_ime = broj.replace("/", "-")
        ime  = f"Parcela_{broj_ime}_{ko}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
        put  = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF","*.pdf"),("Svi","*.*")],
            initialfile=ime, title="Sacuvaj PDF izvestaj"
        )
        if not put: return
        self.btn_pdf.config(state="disabled", text="Generisem PDF...")
        self._st("Generisem PDF...", "#2980b9")

        def _run():
            try:
                generiši_pdf(self.odabrani_rec, self.lat, self.lon, put)
                self.root.after(0, lambda: self._pdf_ok(put))
            except Exception as e:
                import traceback
                self._dbg(traceback.format_exc())
                self.root.after(0, lambda: self._pdf_err(str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _pdf_ok(self, put):
        self.btn_pdf.config(state="normal", text="Generisi PDF izvestaj")
        self._st("PDF izvestaj uspesno generisan!", "#27ae60")
        if messagebox.askyesno("Gotovo!", f"PDF sacuvan:\n{put}\n\nOtvoriti fajl?"):
            os.startfile(put) if os.name == "nt" else webbrowser.open(f"file://{put}")

    def _pdf_err(self, msg):
        self.btn_pdf.config(state="normal", text="Generisi PDF izvestaj")
        self._st(f"Greska pri generisanju PDF-a.", "#c0392b")
        messagebox.showerror("Greska", f"PDF nije generisan:\n{msg}")


if __name__ == "__main__":
    root = tk.Tk()
    ParcelaApp(root)
    root.mainloop()
