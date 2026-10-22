#!/usr/bin/env python3
"""Construit le site d'aide SmartCampus à partir de la documentation Markdown.

Utilisation :
    python3 construire_site.py                      # docs = ../istc-projects/docs
    python3 construire_site.py --docs /chemin/docs  # autre emplacement
    python3 construire_site.py --sortie site        # dossier produit (défaut : site)

Dépendances : pip install markdown pymdown-extensions pyyaml pygments
Facultatif  : mmdc (npm install -g @mermaid-js/mermaid-cli) pour redessiner les
              diagrammes modifiés ; sinon les diagrammes déjà dessinés
              (dossier diagrammes/) sont réutilisés.

Le site produit est statique : il s'ouvre en double-cliquant sur site/index.html
et s'héberge sur n'importe quel serveur web (Nginx, GitHub Pages, Netlify…).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

try:
    import markdown
    import yaml
    from pygments.formatters import HtmlFormatter
except ImportError as exc:  # pragma: no cover
    sys.exit(f"Module manquant ({exc.name}). Installez : pip install markdown pymdown-extensions pyyaml pygments")

ICI = Path(__file__).resolve().parent
MODELE = ICI / "modele"
DIAGRAMMES = ICI / "diagrammes"
SECTIONS = {
    "guide": "Guide d'utilisation",
    "installation": "Installation",
    "developpeurs": "Développeurs",
}

# --------------------------------------------------------------------------- outils


def avertir(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr)


def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn").lower()


def texte_brut(fragment_html: str) -> str:
    t = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", fragment_html, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def url_html(chemin_md: str) -> str:
    return re.sub(r"\.md$", ".html", chemin_md)


def relatif(depuis: str, vers: str) -> str:
    """Lien relatif d'une page (chemin de site) vers une autre."""
    profondeur = depuis.count("/")
    return "../" * profondeur + vers


# --------------------------------------------------------------------------- navigation


class _Chargeur(yaml.SafeLoader):
    pass


_Chargeur.add_multi_constructor("tag:yaml.org,2002:python/", lambda l, s, n: None)


def lire_navigation(fichier_mkdocs: Path):
    conf = yaml.load(fichier_mkdocs.read_text(encoding="utf-8"), Loader=_Chargeur)
    return conf["nav"]


def aplatir(nav, parents=()):
    """Retourne la liste ordonnée des pages : (chemin_md, titre, groupes)."""
    pages = []
    for elt in nav:
        if isinstance(elt, str):
            pages.append((elt, None, parents))
        else:
            ((titre, valeur),) = elt.items()
            if isinstance(valeur, str):
                pages.append((valeur, titre, parents))
            else:
                pages.extend(aplatir(valeur, parents + (titre,)))
    return pages


# --------------------------------------------------------------------------- diagrammes


def dessiner_diagramme(source: str, sortie: Path) -> dict | None:
    """Rend un diagramme mermaid en SVG clair et sombre (cache dans diagrammes/)."""
    cle = hashlib.sha1(source.strip().encode()).hexdigest()[:12]
    fichiers = {mode: DIAGRAMMES / f"{cle}-{mode}.svg" for mode in ("clair", "sombre")}
    manquants = [m for m, f in fichiers.items() if not f.exists()]
    if manquants:
        mmdc = shutil.which("mmdc")
        if not mmdc:
            avertir(f"diagramme {cle} non dessiné (mmdc absent) : affiché en texte")
            return None
        DIAGRAMMES.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            entree = Path(tmp) / "d.mmd"
            entree.write_text(source, encoding="utf-8")
            for mode in manquants:
                conf = ICI / f"mermaid-{mode}.json"
                cmd = [mmdc, "-i", str(entree), "-o", str(fichiers[mode]), "-c", str(conf), "-b", "transparent", "-q"]
                pp = ICI / "puppeteer.json"
                if pp.exists():
                    cmd += ["-p", str(pp)]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode != 0:
                    avertir(f"échec du dessin du diagramme {cle} : {res.stderr.strip()[:200]}")
                    return None
    dest = sortie / "assets" / "diagrammes"
    dest.mkdir(parents=True, exist_ok=True)
    for f in fichiers.values():
        shutil.copy2(f, dest / f.name)
    return {mode: f"assets/diagrammes/{f.name}" for mode, f in fichiers.items()}


# --------------------------------------------------------------------------- conversion


def pygments_recent() -> bool:
    import pygments
    version = tuple(int(x) for x in re.findall(r"\d+", pygments.__version__)[:2])
    return version >= (2, 12)


def extensions():
    if not pygments_recent() and not _DIMS.get("pyg"):
        _DIMS["pyg"] = True
        avertir("Pygments < 2.12 : code affiché sans coloration (pip install -U pygments)")
    return dict(
        extensions=[
            "admonition", "attr_list", "def_list", "footnotes", "md_in_html", "tables",
            "toc", "pymdownx.details", "pymdownx.superfences", "pymdownx.tabbed",
            "pymdownx.tasklist", "pymdownx.keys", "pymdownx.mark", "pymdownx.highlight",
            "pymdownx.inlinehilite",
        ],
        extension_configs={
            "toc": {"permalink": "#", "permalink_title": "Lien vers cette section", "toc_depth": "2-3"},
            "pymdownx.tabbed": {"alternate_style": True},
            "pymdownx.tasklist": {"custom_checkbox": True},
            "pymdownx.highlight": {"css_class": "highlight", "guess_lang": False, "use_pygments": pygments_recent()},
            "pymdownx.keys": {"separator": "+"},
        },
    )


MERMAID = re.compile(r"^```mermaid\n(.*?)\n```\s*$", re.M | re.S)


def convertir_page(chemin_md: str, source: str, sortie: Path, diagrammes: list) -> tuple[str, list, str]:
    """Markdown → (html, toc, titre_h1)."""
    page_url = url_html(chemin_md)

    def remplacer_mermaid(m):
        rendu = dessiner_diagramme(m.group(1), sortie)
        if not rendu:
            return "```text\n" + m.group(1) + "\n```"
        diagrammes.append(rendu)
        clair, sombre = (relatif(page_url, rendu[k]) for k in ("clair", "sombre"))
        return (
            f'<figure class="diagramme" markdown="0">'
            f'<img class="seulement-clair" src="{clair}" alt="Diagramme" loading="lazy">'
            f'<img class="seulement-sombre" src="{sombre}" alt="Diagramme" loading="lazy">'
            f"</figure>"
        )

    source = MERMAID.sub(remplacer_mermaid, source)
    md = markdown.Markdown(**extensions())
    corps = md.convert(source)
    toc = md.toc_tokens

    # titre H1 : retiré du corps (affiché par le gabarit)
    titre = ""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", corps, re.S)
    if m:
        titre = texte_brut(re.sub(r'<a class="headerlink".*?</a>', "", m.group(1)))
        corps = corps[: m.start()] + corps[m.end():]

    # liens .md → .html
    def lien(m):
        cible = m.group(2)
        if re.match(r"^[a-z]+:|^#", cible):
            if cible.startswith("http"):
                return f'{m.group(1)}"{cible}" target="_blank" rel="noopener"'
            return m.group(0)
        cible = re.sub(r"\.md(#|$)", r".html\1", cible)
        cible = re.sub(r"(^|/)$", r"\1index.html", cible)
        return f'{m.group(1)}"{cible}"'

    corps = re.sub(r'(<a href=)"([^"]+)"', lien, corps)

    # images → figures zoomables
    def figure(m):
        attrs = m.group(1)
        alt = re.search(r'alt="([^"]*)"', attrs)
        src = re.search(r'src="([^"]*)"', attrs).group(1)
        legende = alt.group(1) if alt else ""
        taille = ""
        fichier = Path(os.path.normpath((sortie / chemin_md).parent / src))
        dims = dimensions_image(fichier)
        if dims:
            taille = f' width="{dims[0]}" height="{dims[1]}"'
        return (
            f'<figure class="capture"><button type="button" class="zoom" aria-label="Agrandir la capture : {legende}">'
            f'<img src="{src}" alt="{legende}" loading="lazy" decoding="async"{taille}></button>'
            + (f"<figcaption>{legende}</figcaption>" if legende else "")
            + "</figure>"
        )

    corps = re.sub(r"<p>\s*<img([^>]*)/?>\s*</p>", figure, corps)
    # tableaux défilants sur mobile
    corps = re.sub(r"<table>", '<div class="tableau"><table>', corps)
    corps = corps.replace("</table>", "</table></div>")
    # listes à cocher : activées par le script (mémorisées dans le navigateur)
    corps = corps.replace('<input type="checkbox" disabled', '<input type="checkbox"')
    return corps, toc, titre


_DIMS: dict = {}


def dimensions_image(fichier: Path):
    if fichier in _DIMS:
        return _DIMS[fichier]
    dims = None
    try:
        from PIL import Image  # facultatif

        with Image.open(fichier) as im:
            dims = im.size
    except Exception:
        if not fichier.exists():
            avertir(f"image introuvable : {fichier}")
    _DIMS[fichier] = dims
    return dims


def sections_pour_recherche(corps: str, titre: str, url: str, rubrique: str):
    """Découpe une page en sections (h2/h3) pour l'index de recherche."""
    entrees = []
    morceaux = re.split(r'(<h[23] id="[^"]+">.*?</h[23]>)', corps, flags=re.S)
    entrees.append({"p": titre, "s": "", "u": url, "r": rubrique, "x": texte_brut(morceaux[0])[:4000]})
    for i in range(1, len(morceaux), 2):
        m = re.match(r'<h([23]) id="([^"]+)">(.*?)</h[23]>', morceaux[i], re.S)
        intitule = texte_brut(re.sub(r'<a class="headerlink".*?</a>', "", m.group(3)))
        texte = texte_brut(morceaux[i + 1])
        entrees.append({"p": titre, "s": intitule, "u": f"{url}#{m.group(2)}", "r": rubrique, "x": texte[:4000]})
        # questions de la FAQ : une entrée par question
        for q in re.finditer(r"<details[^>]*>\s*<summary>(.*?)</summary>(.*?)</details>", morceaux[i + 1], re.S):
            entrees.append({"p": titre, "s": texte_brut(q.group(1)), "u": f"{url}#{m.group(2)}",
                            "r": rubrique, "x": texte_brut(q.group(2))[:1500], "q": 1})
    return [e for e in entrees if e["x"] or e["s"]]


def lire_glossaire(source: str):
    termes = []
    for m in re.finditer(r"^([^\s:][^\n]*)\n:\s{3}(.+?)(?=\n\n|\Z)", source, re.M | re.S):
        terme, definition = m.group(1).strip(), re.sub(r"\s+", " ", m.group(2)).strip()
        definition = re.sub(r"\*\*?([^*]+)\*\*?", r"\1", definition)
        cle = re.sub(r"\s*\(.*\)$", "", terme)
        termes.append({"t": terme, "c": cle, "d": definition})
    return termes


# --------------------------------------------------------------------------- gabarit

ICONES = {
    "recherche": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "soleil": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "lune": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "fermer": '<path d="M18 6 6 18M6 6l12 12"/>',
    "fleche": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "retour": '<path d="M19 12H5M11 18l-6-6 6-6"/>',
    "chevron": '<path d="m6 9 6 6 6-6"/>',
    "chevron-d": '<path d="m9 6 6 6-6 6"/>',
    "telecharger": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "imprimer": '<path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 14h12v7H6z"/>',
    "haut": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "maison": '<path d="M3 11 12 3l9 8"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    "mail": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    "telephone": '<path d="M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-2"/>',
    "horloge": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "calendrier": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4M7.5 14h.01M12 14h.01M16.5 14h.01M7.5 17.5h.01M12 17.5h.01"/>',
    "etoile": '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
    "ampoule": '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>',
    "casque": '<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="14" width="4" height="6" rx="1.5"/><rect x="17" y="14" width="4" height="6" rx="1.5"/><path d="M19 20c0 1-1.5 2-4 2h-2"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "pouce-haut": '<path d="M7 11v9H4v-9zM7 11l4-8c1.5 0 2.5 1 2.5 2.5V9h5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.3 20H7"/>',
    "pouce-bas": '<path d="M7 13V4H4v9zM7 13l4 8c1.5 0 2.5-1 2.5-2.5V15h5a2 2 0 0 0 2-2.3l-1.2-7A2 2 0 0 0 17.3 4H7"/>',
    "fusee": '<path d="M5 15c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9A2.2 2.2 0 0 0 5 15z"/><path d="m12 15-3-3a22 22 0 0 1 2-4A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.5-6 11a22 22 0 0 1-4 2z"/><path d="M9 12H4s.6-3 2-4c1.6-1.1 5 0 5 0M12 15v5s3-.6 4-2c1.1-1.6 0-5 0-5"/>',
    "livre-ouvert": '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2zM22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
    "document": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
    "carte": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/>',
    "engrenage": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    "cible": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "niveau": '<path d="M5 20v-5M10 20v-9M15 20V7M20 20V3"/>',
    "inscription": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 18v-6M9 15h6"/>',
    "etudiant": '<path d="M22 10 12 5 2 10l10 5 10-5z"/><path d="M6 12v5c3 2 9 2 12 0v-5"/>',
    "formateur": '<rect x="3" y="4" width="18" height="12" rx="1"/><path d="M8 20h8M12 16v4"/>',
    "pointage": '<rect x="4" y="4" width="16" height="17" rx="2"/><path d="M9 2h6v4H9zM9 13l2 2 4-4"/>',
    "dossier": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "livre": '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 19.5V21.5M20 19v3H6.5"/>',
    "finance": '<rect x="2" y="6" width="20" height="13" rx="2"/><circle cx="12" cy="12.5" r="3"/><path d="M6 10v5M18 10v5"/>',
    "equipe": '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c0-3.5 3-6 7-6s7 2.5 7 6"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14c2.5.6 4 2.8 4 6"/>',
    "carton": '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    "bouclier": '<path d="M12 2 4 5v6c0 5 3.5 9.5 8 11 4.5-1.5 8-6 8-11V5z"/><path d="m9 12 2 2 4-4"/>',
    "serveur": '<rect x="3" y="3" width="18" height="7" rx="1.5"/><rect x="3" y="14" width="18" height="7" rx="1.5"/><path d="M7 6.5h.01M7 17.5h.01"/>',
    "code": '<path d="m8 6-6 6 6 6M16 6l6 6-6 6"/>',
    "parcours": '<circle cx="6" cy="19" r="2.5"/><circle cx="18" cy="5" r="2.5"/><path d="M8.5 19H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5"/>',
}


COURANT = ' aria-current="page"'
ACTIF = ' aria-current="true"'
SEPARATEUR = ' <span class="sep" aria-hidden="true">›</span> '
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def icone(nom: str, classe: str = "ic") -> str:
    return (f'<svg class="{classe}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONES[nom]}</svg>')


def esc(t: str) -> str:
    return html.escape(t, quote=True)


def date_fr(d: dt.date) -> str:
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def pastille_cat(cat, classe="cat-ic") -> str:
    return f'<span class="{classe} c-{cat["couleur"]}">{icone(cat["icone"])}</span>'


def lien_contact(conf, racine):
    """(href, libellé) du bouton « Nous contacter »."""
    contact = conf.get("contact") or {}
    if contact.get("email"):
        return f'mailto:{contact["email"]}', contact["email"]
    if contact.get("telephone"):
        return f'tel:{re.sub(r"[^0-9+]", "", contact["telephone"])}', contact["telephone"]
    return f"{racine}guide/faq.html", ""


def carte_besoin_aide(conf, racine, classe="carte-aide"):
    href, _ = lien_contact(conf, racine)
    contact = conf.get("contact") or {}
    autres = []
    if contact.get("telephone") and contact.get("email"):
        autres.append(f'<a href="tel:{re.sub(r"[^0-9+]", "", contact["telephone"])}">{icone("telephone")} {esc(contact["telephone"])}</a>')
    autres.append(f'<a href="{racine}guide/faq.html">Consulter la FAQ</a>')
    return (f'<section class="{classe}" aria-label="Besoin d\'aide">'
            f'<p class="ca-titre"><span class="ca-ic">{icone("casque")}</span>Besoin d\'aide ?</p>'
            f'<p>Notre équipe est là pour vous accompagner.</p>'
            f'<a class="btn-contour" href="{href}">{icone("mail")} Contacter le support</a>'
            f'<p class="ca-autres">{" · ".join(autres)}</p></section>')


def construire_nav_html(categories, page_url, racine, cat_courante):
    """Barre latérale : les rubriques (catégories) et leurs articles."""
    blocs = []
    for cat in categories:
        ouvert = " open" if cat_courante is cat else ""
        url_cat = f"rubriques/{cat['id']}.html"
        courant_cat = COURANT if page_url == url_cat else ""
        articles = "".join(
            f'<li><a href="{racine}{p["url"]}" data-page="{p["url"]}"{COURANT if p["url"] == page_url else ""}>{esc(p["titre_nav"])}</a></li>'
            for p in cat["pages_obj"]
        )
        blocs.append(
            f'<li class="cat"><details{ouvert}><summary>{pastille_cat(cat)}'
            f'<a href="{racine}{url_cat}"{courant_cat}>{esc(cat["titre"])}</a>'
            f'<span class="cat-chevron">{icone("chevron")}</span></summary>'
            f'<ul>{articles}</ul></details></li>'
        )
    return (f'<button type="button" class="nav-recherche" data-ouvrir-recherche>{icone("recherche")}<span>Rechercher dans les rubriques…</span></button>'
            f'<p class="nav-titre">Rubriques</p><ul class="nav-arbre">{"".join(blocs)}</ul>')


def toc_html(toc):
    def rec(items, niveau=0):
        if not items:
            return ""
        lis = []
        for it in items:
            if it["level"] > 3:
                continue
            nom = esc(texte_brut(it["name"]))
            lis.append(f'<li><a href="#{it["id"]}">{nom}</a>{rec(it.get("children", []), niveau + 1)}</li>')
        return f"<ul>{''.join(lis)}</ul>" if lis else ""

    racines = []
    for it in toc:  # le H1 porte les H2 en enfants
        racines.extend(it.get("children", []) if it["level"] == 1 else [it])
    contenu = rec(racines)
    if not contenu:
        return ""
    return f'<nav class="toc" aria-label="Dans cet article"><p class="toc-titre">Dans cet article</p>{contenu}</nav>'


def gabarit(conf, *, titre_page, page_url, contenu, nav, colonne="", fil="", bandeau="", pied_page="", classe="", description=""):
    racine = "../" * page_url.count("/")
    liens = [("Accueil", "index.html", page_url == "index.html"),
             ("Rubriques", "index.html#rubriques", page_url.startswith("rubriques/")),
             ("Guide", "guide/index.html", page_url.startswith("guide/") and not page_url.endswith("faq.html")),
             ("Installation", "installation/index.html", page_url.startswith("installation/")),
             ("Développeurs", "developpeurs/index.html", page_url.startswith("developpeurs/")),
             ("FAQ", "guide/faq.html", page_url.endswith("faq.html"))]
    onglets = "".join(f'<a href="{racine}{u}" class="onglet"{ACTIF if a else ""}>{esc(n)}</a>' for n, u, a in liens)
    word = conf.get("fichier_word_url")
    lien_word = (f'<a class="btn-icone" href="{racine}{word}" title="Télécharger la version Word" download>'
                 f'{icone("telecharger")}<span class="sr">Version Word</span></a>') if word else ""
    href_contact, _ = lien_contact(conf, racine)
    titre_complet = conf["titre"] if page_url == "index.html" else f"{titre_page} · {conf['nom_court']}"
    marque = (f'<a class="marque" href="{racine}index.html" aria-label="{esc(conf["titre"])} — accueil">'
              f'<img src="{racine}assets/logo.png" alt="SmartCampus" width="260" height="151">'
              f'<span class="marque-texte"><strong>Centre d\'aide</strong><small>{esc(conf.get("slogan", ""))}</small></span></a>')
    pied_liens = "".join(f'<a href="{racine}{u}">{esc(n)}</a>' for n, u, _ in liens)
    return f"""<!doctype html>
<html lang="fr" data-racine="{racine}" data-page="{page_url}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(titre_complet)}</title>
<meta name="description" content="{esc(description or conf['sous_titre'])}">
<meta name="theme-color" content="#1d63e0">
<link rel="icon" href="{racine}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{racine}assets/style.css">
<script>try{{var t=localStorage.getItem('aide-theme');if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
</head>
<body class="{classe}">
<a class="evitement" href="#contenu">Aller au contenu</a>
<header class="barre">
 <div class="barre-int">
  <button class="btn-icone seulement-mobile" id="ouvrir-nav" aria-label="Ouvrir le menu" aria-controls="nav" aria-expanded="false">{icone("menu")}</button>
  {marque}
  <nav class="onglets" aria-label="Menu principal">{onglets}</nav>
  <button class="champ-recherche" id="ouvrir-recherche" type="button" aria-label="Rechercher dans l'aide">
    {icone("recherche")}<span>Rechercher dans l'aide…</span><kbd>/</kbd>
  </button>
  {lien_word}
  <button class="btn-icone" id="theme" type="button" aria-label="Changer de thème">{icone("lune", "ic ic-lune")}{icone("soleil", "ic ic-soleil")}</button>
  <a class="btn-principal btn-contact" href="{href_contact}">{icone("mail")}<span>Nous contacter</span></a>
 </div>
</header>
{bandeau}
<div class="cadre{' sans-colonne' if not colonne else ''}">
  <aside class="nav" id="nav" aria-label="Navigation">
    <nav class="onglets-mobile" aria-label="Menu principal">{onglets}</nav>
    {nav}
  </aside>
  <main id="contenu" tabindex="-1">
    <article class="page">
      {fil}
      <div id="bandeau-parcours"></div>
      {contenu}
    </article>
    {pied_page}
  </main>
  {f'<aside class="colonne-droite">{colonne}</aside>' if colonne else ""}
</div>
<footer class="pied">
  <div class="pied-int">
    <a class="marque" href="{racine}index.html"><img src="{racine}assets/logo.png" alt="SmartCampus" width="260" height="151" loading="lazy">
      <span class="marque-texte"><strong>Centre d'aide</strong><small>{esc(conf.get("slogan", ""))}</small></span></a>
    <nav class="pied-liens" aria-label="Liens du pied de page">{pied_liens}<a href="{href_contact}">Nous contacter</a></nav>
    <div class="pied-droite">
      <p>© {dt.date.today().year} SmartCampus. Tous droits réservés.</p>
      <p>Mis à jour le {dt.date.today().strftime("%d/%m/%Y")} · <button type="button" class="lien-discret" onclick="window.print()">{icone("imprimer")} Imprimer</button></p>
    </div>
  </div>
</footer>
<div class="voile" id="voile" hidden></div>
<script src="{racine}assets/donnees.js"></script>
<script src="{racine}assets/app.js"></script>
</body>
</html>
"""


# --------------------------------------------------------------------------- bandeaux (hero)


def ecran_portable(src: str, alt: str, classe="portable") -> str:
    return (f'<div class="{classe}" aria-hidden="true"><div class="portable-ecran">'
            f'<img src="{src}" alt="{esc(alt)}" loading="lazy" decoding="async"></div><div class="portable-socle"></div></div>')


def bandeau_article(conf, racine):
    capture = conf.get("capture_accueil")
    visuel = ecran_portable(racine + capture, "Tableau de bord SmartCampus", "portable petit") if capture else ""
    return f"""<section class="bandeau bandeau-article" aria-label="Centre d'aide">
  <div class="bandeau-int">
    <div class="bandeau-texte">
      <p class="surtitre">Centre d'aide</p>
      <p class="bandeau-titre">Des réponses claires pour <span class="accent">aller plus loin</span></p>
      <p class="bandeau-sous">Des guides pas à pas, des conseils pratiques et des tutoriels pour bien utiliser SmartCampus.</p>
    </div>
    <p class="manuscrit" aria-hidden="true"><span>Apprendre</span><span>Gérer</span><span>Suivre</span><span>Réussir</span></p>
    {visuel}
    <p class="post-it" aria-hidden="true">Une école mieux gérée pour un meilleur avenir</p>
  </div>
</section>"""


def bandeau_rubrique(cat, nb, minutes, fil):
    return f"""<section class="bandeau bandeau-rubrique c-{cat['couleur']}">
  <div class="bandeau-int">
    <div class="bandeau-texte">
      {fil}
      <p class="pilule">{icone(cat['icone'])} Centre d'aide</p>
      <h1>{esc(cat['titre'])}</h1>
      <p class="bandeau-sous">{esc(cat['resume'])}</p>
    </div>
    <div class="visuel-rubrique" aria-hidden="true">
      <span class="vr-cercle"></span>
      <span class="vr-icone">{icone(cat['icone'])}</span>
      <span class="flottant f1">{icone('livre-ouvert')}<span><strong>{nb} article{'s' if nb > 1 else ''}</strong> pas à pas</span></span>
      <span class="flottant f2">{icone('horloge')}<span><strong>{minutes} min</strong> de lecture au total</span></span>
    </div>
  </div>
</section>"""


# --------------------------------------------------------------------------- pages spéciales


def carte_article(p, racine, info, cat):
    return (f'<li><a class="carte-article" href="{racine}{p["url"]}">{pastille_cat(cat, "ca-pastille")}'
            f'<span class="ca-corps"><span class="ca-nom">{esc(p["titre"])}</span>'
            f'<span class="ca-desc">{esc(info["resume"])}</span>'
            f'<span class="ca-meta">{icone("horloge")} {info["minutes"]} min de lecture</span></span>'
            f'{icone("fleche", "ic ca-fleche")}</a></li>')


def liste_numerotee(items, classe="liste-num"):
    return f'<ol class="{classe}">' + "".join(
        f'<li><a href="{u}"><span class="num">{i}</span><span class="ln-texte">{esc(t)}</span>{icone("fleche")}</a></li>'
        for i, (t, u) in enumerate(items, 1)) + "</ol>"


def page_rubrique(conf, cat, racine, infos, taches, parcours_conf, pages_par_md):
    articles = "".join(carte_article(p, racine, infos[p["url"]], cat) for p in cat["pages_obj"])
    contenu = f"""
<p class="pilule c-{cat['couleur']}">{icone(cat['icone'])} {esc(cat['titre'])}</p>
<div class="titre-ligne"><h2 class="titre-section">Articles de cette rubrique</h2></div>
<p class="sous-titre-section">Tous les guides pour « {esc(cat['titre'].lower())} », dans l'ordre conseillé de lecture.</p>
<ul class="liste-articles">{articles}</ul>
"""
    # colonne droite : tâches fréquentes de la rubrique, parcours recommandé, aide
    urls = {p["url"] for p in cat["pages_obj"]}
    pop = [(t, racine + u) for (t, u, page) in taches if page in urls] or [(t, racine + u) for (t, u, _) in taches[:5]]
    colonne = (f'<section class="carte-cote"><p class="cc-titre">{icone("etoile", "ic ic-etoile")} Articles populaires</p>'
               f'{liste_numerotee(pop[:6], "liste-num compacte")}</section>')
    prof = next((pr for pr in conf["profils"] if pr["id"] == cat.get("profil")), None)
    if prof:
        etapes = [pages_par_md[m] for m in prof["pages"] if m in pages_par_md]
        lis = "".join(f'<li><a href="{racine}{p["url"]}" data-page="{p["url"]}">{icone("check")}<span>{i}. {esc(p["titre"])}</span></a></li>'
                      for i, p in enumerate(etapes[:6], 1))
        colonne += (f'<section class="carte-cote carte-parcours"><p class="cc-titre">{icone("livre-ouvert")} Parcours recommandé</p>'
                    f'<p class="cc-sous">Profil « {esc(prof["titre"])} » : {esc(prof["resume"][0].lower() + prof["resume"][1:])}</p>'
                    f'<ul class="parcours-coches">{lis}</ul>'
                    f'<a class="btn-contour" href="{racine}index.html?profil={prof["id"]}#titre-profils">Voir le parcours complet {icone("fleche")}</a></section>')
    colonne += carte_besoin_aide(conf, racine)
    return contenu, colonne


def page_accueil(conf, categories, racine, infos, taches, corps_index):
    corps_index = re.sub(r'<div class="admonition[^"]*">\s*<p class="admonition-title">Version Word</p>.*?</div>', "", corps_index, count=1, flags=re.S)
    profils = "".join(
        f'<button type="button" class="carte-profil" data-profil="{p["id"]}" aria-pressed="false">'
        f'<span class="pastille">{icone(p["icone"])}</span>'
        f'<span class="profil-titre">{esc(p["titre"])}</span>'
        f'<span class="profil-resume">{esc(p["resume"])}</span>'
        f'<span class="profil-etapes">{len(p["pages"])} pages à lire</span></button>'
        for p in conf["profils"])
    cartes = []
    for cat in categories:
        nb = len(cat["pages_obj"])
        cartes.append(
            f'<a class="carte-rubrique{" technique" if cat.get("technique") else ""}" href="rubriques/{cat["id"]}.html">'
            f'{pastille_cat(cat, "cr-pastille")}<span class="cr-nom">{esc(cat["titre"])}</span>'
            f'<span class="cr-desc">{esc(cat["resume"])}</span>'
            f'<span class="cr-pied"><span>{nb} article{"s" if nb > 1 else ""}</span>{icone("fleche")}</span></a>')
    principales = "".join(c for c, cat in zip(cartes, categories) if not cat.get("technique"))
    techniques = "".join(c for c, cat in zip(cartes, categories) if cat.get("technique"))
    moitie = (len(taches) + 1) // 2
    pop_g = liste_numerotee([(t, u) for t, u, _ in taches[:moitie]])
    pop_d = f'<ol class="liste-num" start="{moitie + 1}">' + "".join(
        f'<li><a href="{u}"><span class="num">{i}</span><span class="ln-texte">{esc(t)}</span>{icone("fleche")}</a></li>'
        for i, (t, u, _) in enumerate(taches[moitie:], moitie + 1)) + "</ol>"
    exemples = ", ".join(conf["recherches_suggerees"])
    puces = "".join(f'<button type="button" class="puce" data-recherche="{esc(s)}">{esc(s)}</button>' for s in conf["recherches_suggerees"])
    capture = conf.get("capture_accueil")
    word = conf.get("fichier_word_url")
    href_contact, _ = lien_contact(conf, racine)
    return f"""
<section class="hero">
  <div class="hero-int">
    <div class="hero-texte">
      <p class="pilule">Centre d'aide</p>
      <h1>Comment <span class="insec">pouvons-nous</span> <span class="accent">vous aider ?</span></h1>
      <p class="hero-sous">Retrouvez ici toutes les réponses pour bien utiliser SmartCampus.</p>
      <form class="hero-recherche" id="hero-recherche" role="search">
        {icone("recherche")}
        <input type="search" id="hero-q" placeholder="Rechercher une question, une fonctionnalité…" aria-label="Rechercher dans l'aide" autocomplete="off">
        <button type="submit" class="btn-principal">Rechercher</button>
      </form>
      <div class="puces" aria-label="Exemples de recherches"><span class="puces-libelle">Exemples :</span>{puces}</div>
    </div>
    <div class="hero-visuel" aria-hidden="true">
      <span class="blob b1"></span><span class="blob b2"></span>
      {ecran_portable(capture, "Tableau de bord SmartCampus") if capture else ""}
      <span class="flottant f1 c-vert">{icone("equipe")}<span>Des guides<br>pratiques</span></span>
      <span class="flottant f2 c-rose">{icone("ampoule")}<span>Des réponses<br>rapides</span></span>
      <span class="flottant f3 c-bleu">{icone("livre-ouvert")}<span>Une prise<br>en main facile</span></span>
    </div>
  </div>
</section>

<section class="bloc" id="rubriques" aria-labelledby="titre-rubriques">
  <div class="bloc-entete"><div><h2 id="titre-rubriques">Parcourir les rubriques</h2><p>Explorez nos guides et tutoriels par thème pour trouver rapidement ce dont vous avez besoin.</p></div>
    <a class="lien-fleche" href="guide/index.html">Voir tout le guide {icone("fleche")}</a></div>
  <div class="grille-rubriques">{principales}</div>
</section>

<section class="bloc bloc-teinte" aria-labelledby="titre-taches">
  <div class="bloc-entete"><div><h2 id="titre-taches">Articles populaires</h2><p>Accédez directement à la bonne section des procédures les plus demandées.</p></div>
    <button type="button" class="lien-fleche" data-ouvrir-recherche>Rechercher un article {icone("fleche")}</button></div>
  <div class="deux-colonnes">{pop_g}{pop_d}</div>
</section>

<section class="bloc" aria-labelledby="titre-profils">
  <div class="bloc-entete"><div><h2 id="titre-profils">Je suis…</h2><p>Un parcours de lecture adapté à votre rôle. Votre progression est mémorisée sur cet appareil.</p></div></div>
  <div class="grille-profils">{profils}</div>
  <div id="detail-parcours" class="detail-parcours" hidden></div>
</section>

<section class="bloc" aria-labelledby="titre-technique">
  <div class="bloc-entete"><div><h2 id="titre-technique">Pour les équipes techniques</h2><p>Installer, maintenir et faire évoluer la plateforme.</p></div>
    {f'<a class="lien-fleche" href="{word}" download>{icone("telecharger")} Toute la documentation en Word</a>' if word else ""}</div>
  <div class="grille-rubriques deux">{techniques}</div>
</section>

<section class="bloc support" id="support" aria-labelledby="titre-support">
  <div class="support-texte">
    <p class="support-sur">Vous ne trouvez pas la réponse ?</p>
    <h2 id="titre-support">Notre équipe est là pour vous aider</h2>
    <p>Contactez notre support et nous vous répondrons dans les plus brefs délais.</p>
    <div class="support-actions">
      <a class="btn-vert" href="{href_contact}">{icone("mail")} Contacter le support</a>
      <a class="btn-secondaire" href="guide/faq.html">Consulter la FAQ</a>
    </div>
  </div>
  <div class="support-visuel" aria-hidden="true">
    <span class="sv-cercle"></span>
    <span class="sv-casque">{icone("casque")}</span>
    <span class="sv-bulle">Une question ?<br>On est là !</span>
  </div>
</section>

<section class="bloc contenu-accueil" aria-labelledby="titre-apropos">
  <details class="en-bref"><summary><h2 id="titre-apropos">La plateforme en bref</h2><span>Ce que fait SmartCampus, en quelques minutes de lecture</span></summary>
  <div class="en-bref-corps">{corps_index}</div></details>
</section>
"""


# --------------------------------------------------------------------------- principal


def resume_page(corps: str) -> str:
    for m in re.finditer(r"<p>(.*?)</p>", corps, re.S):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip()
        if len(t) > 40 and not re.match(r"^(Menu|Accès|Rôle|Pour qui)\s*:", t):
            return t if len(t) <= 150 else t[:147].rsplit(" ", 1)[0] + "…"
    return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", default=str(ICI.parent / "istc-projects" / "docs"), help="dossier docs/ du projet")
    ap.add_argument("--mkdocs", default=None, help="mkdocs.yml (défaut : à côté de docs/)")
    ap.add_argument("--sortie", default=str(ICI / "site"), help="dossier du site produit")
    args = ap.parse_args()

    docs = Path(args.docs).resolve()
    mkdocs = Path(args.mkdocs) if args.mkdocs else docs.parent / "mkdocs.yml"
    sortie = Path(args.sortie).resolve()
    if not docs.is_dir() or not mkdocs.exists():
        sys.exit(f"Documentation introuvable : {docs} (et {mkdocs}). Utilisez --docs.")
    conf = json.loads((ICI / "config_site.json").read_text(encoding="utf-8"))
    print(f"Documentation : {docs}\nSite produit  : {sortie}")

    if sortie.exists():
        shutil.rmtree(sortie)
    (sortie / "assets").mkdir(parents=True)
    for f in MODELE.iterdir():
        if f.is_file() and not f.name.startswith("."):
            shutil.copy2(f, sortie / "assets" / f.name)
    # coloration du code (clair / sombre)
    def style_code(*noms):
        from pygments.styles import get_all_styles
        dispo = set(get_all_styles())
        return next((n for n in noms if n in dispo), "default")

    clair, sombre = style_code("friendly", "default"), style_code("github-dark", "monokai", "native")
    css_code = (HtmlFormatter(style=clair).get_style_defs(":root .highlight")
                + "\n" + HtmlFormatter(style=sombre).get_style_defs(":root[data-theme=dark] .highlight")
                + "\n@media (prefers-color-scheme: dark){"
                + HtmlFormatter(style=sombre).get_style_defs(":root:not([data-theme=light]) .highlight") + "}")
    (sortie / "assets" / "code.css").write_text(css_code, encoding="utf-8")

    # fichiers non Markdown (captures, fichier Word…)
    for f in docs.rglob("*"):
        if f.is_file() and f.suffix.lower() != ".md" and not f.name.startswith("."):
            dest = sortie / f.relative_to(docs)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
    if (docs / conf.get("fichier_word", "-")).exists():
        conf["fichier_word_url"] = conf["fichier_word"]
    if conf.get("capture_accueil") and not (sortie / conf["capture_accueil"]).exists():
        avertir(f"capture d'accueil introuvable : {conf['capture_accueil']}")
        conf["capture_accueil"] = ""

    pages = []
    for md, titre_nav, groupes in aplatir(lire_navigation(mkdocs)):
        if not (docs / md).exists():
            avertir(f"page de la navigation absente : {md}")
            continue
        rubrique = md.split("/")[0] if "/" in md else None
        pages.append({"md": md, "url": url_html(md), "titre_nav": titre_nav, "groupes": groupes, "rubrique": rubrique})
    pages_par_md = {p["md"]: p for p in pages}

    # 1re passe : conversion
    index_recherche, ancres, diagrammes = [], [], []
    infos = {}
    for p in pages:
        source_md = docs / p["md"]
        corps, toc, titre = convertir_page(p["md"], source_md.read_text(encoding="utf-8"), sortie, diagrammes)
        p.update(corps=corps, toc=toc, titre=titre or p["titre_nav"] or p["md"])
        if not p["titre_nav"]:
            p["titre_nav"] = "Présentation" if p["md"].endswith("index.md") and p["md"] != "index.md" else p["titre"]
        rubrique_nom = SECTIONS.get(p["rubrique"], "Accueil")
        index_recherche += sections_pour_recherche(corps, p["titre"], p["url"], rubrique_nom)
        for m in re.finditer(r'<h[23] id="([^"]+)">(.*?)</h[23]>', corps, re.S):
            ancres.append((p["url"], texte_brut(re.sub(r'<a class="headerlink".*?</a>', "", m.group(2))), m.group(1)))
        nb_mots = len(texte_brut(corps).split())
        infos[p["url"]] = {"minutes": max(1, round(nb_mots / 200)), "resume": resume_page(corps),
                           "maj": dt.date.fromtimestamp(source_md.stat().st_mtime)}

    # catégories (rubriques thématiques)
    categories, cat_de_page = [], {}
    for cat in conf.get("categories", []):
        cat = dict(cat)
        cat["pages_obj"] = []
        for m in cat["pages"]:
            if m not in pages_par_md:
                avertir(f"rubrique {cat['id']} : page {m} absente")
                continue
            cat["pages_obj"].append(pages_par_md[m])
            cat_de_page.setdefault(pages_par_md[m]["url"], cat)
        categories.append(cat)
    for p in pages:
        if p["md"] != "index.md" and p["url"] not in cat_de_page:
            avertir(f"page sans rubrique dans config_site.json : {p['md']}")

    # tâches fréquentes : (libellé, url avec ancre, url de page)
    taches = []
    for libelle, md, titre_section in conf["taches"]:
        page = pages_par_md.get(md)
        if not page:
            avertir(f"tâche « {libelle} » : page {md} absente")
            continue
        ancre = next((a for (u, t, a) in ancres if u == page["url"] and sans_accents(titre_section) in sans_accents(t)), None)
        if ancre is None:
            avertir(f"tâche « {libelle} » : section « {titre_section} » introuvable dans {md}")
        taches.append((libelle, page["url"] + (f"#{ancre}" if ancre else ""), page["url"]))

    glossaire = lire_glossaire((docs / "guide/glossaire.md").read_text(encoding="utf-8")) if (docs / "guide/glossaire.md").exists() else []
    parcours = {
        pr["id"]: {"titre": pr["titre"], "pages": [{"u": pages_par_md[m]["url"], "t": pages_par_md[m]["titre"]} for m in pr["pages"] if m in pages_par_md]}
        for pr in conf["profils"]
    }
    for pr in conf["profils"]:
        for m in pr["pages"]:
            if m not in pages_par_md:
                avertir(f"profil {pr['id']} : page {m} absente")
    donnees = {"recherche": index_recherche, "glossaire": glossaire, "parcours": parcours,
               "pages": [{"u": p["url"], "t": p["titre"]} for p in pages]}
    (sortie / "assets" / "donnees.js").write_text("window.AIDE=" + json.dumps(donnees, ensure_ascii=False, separators=(",", ":")) + ";", encoding="utf-8")

    # 2e passe : écriture des pages
    lineaire = [p for p in pages if p["md"] != "index.md"]
    for p in pages:
        racine = "../" * p["url"].count("/")
        cat = cat_de_page.get(p["url"])
        nav = construire_nav_html(categories, p["url"], racine, cat)
        if p["md"] == "index.md":
            contenu = page_accueil(conf, categories, racine, infos, taches, p["corps"])
            html_page = gabarit(conf, titre_page=conf["titre"], page_url=p["url"], contenu=contenu, nav=nav, classe="accueil")
        else:
            i = lineaire.index(p)
            prec = lineaire[i - 1] if i > 0 else None
            suiv = lineaire[i + 1] if i + 1 < len(lineaire) else None
            pied = '<nav class="prec-suiv" aria-label="Pages voisines">'
            if prec:
                pied += f'<a class="prec" href="{racine}{prec["url"]}"><span>{icone("retour")} Précédent</span><strong>{esc(prec["titre"])}</strong></a>'
            if suiv:
                pied += f'<a class="suiv" href="{racine}{suiv["url"]}"><span>Suivant {icone("fleche")}</span><strong>{esc(suiv["titre"])}</strong></a>'
            pied += "</nav>"
            miettes = [f'<a href="{racine}index.html">{icone("maison")}<span>Accueil</span></a>']
            if cat:
                miettes.append(f'<a href="{racine}rubriques/{cat["id"]}.html">{esc(cat["titre"])}</a>')
            miettes.append(f'<span aria-current="page">{esc(p["titre_nav"])}</span>')
            fil = f'<nav class="fil" aria-label="Fil d’Ariane">{SEPARATEUR.join(miettes)}</nav>'
            info = infos[p["url"]]
            entete = (
                (f'<p class="pilule c-{cat["couleur"]}"><a href="{racine}rubriques/{cat["id"]}.html">{icone(cat["icone"])} {esc(cat["titre"])}</a></p>' if cat else "")
                + f'<h1>{esc(p["titre"])}</h1>'
                + f'<p class="meta-article"><span>{icone("horloge")} {info["minutes"]} min de lecture</span>'
                + f'<span>{icone("calendrier")} Mise à jour le {date_fr(info["maj"])}</span>'
                + f'<button type="button" class="lien-discret" onclick="window.print()">{icone("imprimer")} Imprimer</button></p>'
            )
            avis = ('<section class="avis" aria-label="Votre avis"><div><p class="avis-titre">Cet article vous a-t-il été utile ?</p>'
                    '<p class="avis-sous">Votre retour nous aide à améliorer nos guides.</p></div>'
                    f'<div class="avis-boutons"><button type="button" class="btn-avis oui" data-avis="oui">{icone("pouce-haut")} Oui</button>'
                    f'<button type="button" class="btn-avis non" data-avis="non">{icone("pouce-bas")} Non</button></div></section>')
            colonne = toc_html(p["toc"])
            colonne = (f'<section class="carte-cote carte-toc">{colonne}</section>' if colonne else "") + carte_besoin_aide(conf, racine)
            description = info["resume"] or next((e["x"][:160] for e in index_recherche if e["u"] == p["url"]), "")
            classes = "article" + (" page-glossaire" if p["md"].endswith("glossaire.md") else "")
            html_page = gabarit(conf, titre_page=p["titre"], page_url=p["url"], contenu=entete + p["corps"] + avis, nav=nav,
                                colonne=colonne, fil=fil, bandeau=bandeau_article(conf, racine), pied_page=pied,
                                description=description, classe=classes)
        dest = sortie / p["url"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html_page, encoding="utf-8")

    # pages de rubrique
    (sortie / "rubriques").mkdir(exist_ok=True)
    for cat in categories:
        url = f"rubriques/{cat['id']}.html"
        racine = "../"
        nb = len(cat["pages_obj"])
        minutes = sum(infos[q["url"]]["minutes"] for q in cat["pages_obj"])
        fil = (f'<nav class="fil" aria-label="Fil d’Ariane"><a href="{racine}index.html">{icone("maison")}<span>Accueil</span></a>'
               f'{SEPARATEUR}<span aria-current="page">{esc(cat["titre"])}</span></nav>')
        contenu, colonne = page_rubrique(conf, cat, racine, infos, taches, parcours, pages_par_md)
        html_page = gabarit(conf, titre_page=cat["titre"], page_url=url, contenu=contenu,
                            nav=construire_nav_html(categories, url, racine, cat), colonne=colonne,
                            bandeau=bandeau_rubrique(cat, nb, minutes, fil), classe="rubrique", description=cat["resume"])
        (sortie / url).write_text(html_page, encoding="utf-8")

    # page 404 (serveurs web)
    (sortie / "404.html").write_text(gabarit(conf, titre_page="Page introuvable", page_url="404.html",
        contenu='<h1>Page introuvable</h1><p>Cette page n\'existe pas ou a été déplacée.</p><p><a class="btn-principal" href="index.html">Retour à l\'accueil</a> '
                '<button type="button" class="btn-secondaire" data-ouvrir-recherche>Rechercher</button></p>',
        nav=construire_nav_html(categories, "404.html", "", None), classe="article"), encoding="utf-8")
    print(f"{len(pages)} pages, {len(categories)} rubriques, {len(index_recherche)} entrées de recherche, "
          f"{len(glossaire)} termes du glossaire, {len(diagrammes)} diagrammes → {sortie / 'index.html'}")


if __name__ == "__main__":
    main()
