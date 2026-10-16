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
    "telecharger": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "imprimer": '<path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><path d="M6 14h12v7H6z"/>',
    "haut": '<path d="M12 19V5M6 11l6-6 6 6"/>',
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
SEPARATEUR = ' <span aria-hidden="true">›</span> '


def icone(nom: str, classe: str = "ic") -> str:
    return (f'<svg class="{classe}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONES[nom]}</svg>')


def esc(t: str) -> str:
    return html.escape(t, quote=True)


def construire_nav_html(pages, page_url, racine):
    """Barre latérale : arborescence de la rubrique courante."""
    rubrique = page_url.split("/")[0] if "/" in page_url else None
    blocs, groupe_ouvert = [], None
    for p in pages:
        if p["rubrique"] != rubrique:
            continue
        groupes = p["groupes"][1:]  # sans la rubrique elle-même
        groupe = groupes[0] if groupes else None
        if groupe != groupe_ouvert:
            if groupe_ouvert is not None:
                blocs.append("</ul></details></li>")
            if groupe is not None:
                ouvert = " open" if any(q["url"] == page_url and q["groupes"][1:2] == (groupe,) for q in pages) else ""
                index_groupe = p["url"] if p["url"].endswith("index.html") else None
                titre_g = (f'<a href="{racine}{index_groupe}" data-page="{index_groupe}"'
                           f'{COURANT if index_groupe == page_url else ""}>{esc(groupe)}</a>'
                           if index_groupe else esc(groupe))
                blocs.append(f'<li class="groupe"><details{ouvert}><summary>{titre_g}</summary><ul>')
            groupe_ouvert = groupe
            if groupe is not None and p["url"].endswith("index.html"):
                continue
        courant = ' aria-current="page"' if p["url"] == page_url else ""
        blocs.append(f'<li><a href="{racine}{p["url"]}" data-page="{p["url"]}"{courant}>{esc(p["titre_nav"])}</a></li>')
    if groupe_ouvert is not None:
        blocs.append("</ul></details></li>")
    if not blocs:  # accueil : les trois rubriques
        for cle, nom in SECTIONS.items():
            blocs.append(f'<li class="titre-rubrique"><a href="{racine}{cle}/index.html">{esc(nom)}</a></li>')
    titre = SECTIONS.get(rubrique, "Sommaire")
    return f'<p class="nav-titre">{esc(titre)}</p><ul class="nav-arbre">{"".join(blocs)}</ul>'


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
    return f'<nav class="toc" aria-label="Sur cette page"><p class="toc-titre">Sur cette page</p>{contenu}</nav>'


def gabarit(conf, *, titre_page, page_url, contenu, nav, toc="", fil="", entete="", pied_page="", classe="", description=""):
    racine = "../" * page_url.count("/")
    onglets = "".join(
        f'<a href="{racine}{cle}/index.html" class="onglet"{ACTIF if page_url.startswith(cle + "/") else ""}>{esc(nom)}</a>'
        for cle, nom in SECTIONS.items()
    )
    word = conf.get("fichier_word_url")
    lien_word = (f'<a class="btn-icone" href="{racine}{word}" title="Télécharger la version Word" download>'
                 f'{icone("telecharger")}<span class="sr">Version Word</span></a>') if word else ""
    titre_complet = conf["titre"] if page_url == "index.html" else f"{titre_page} · {conf['nom_court']}"
    return f"""<!doctype html>
<html lang="fr" data-racine="{racine}" data-page="{page_url}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(titre_complet)}</title>
<meta name="description" content="{esc(description or conf['sous_titre'])}">
<link rel="icon" href="{racine}assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{racine}assets/style.css">
<script>try{{var t=localStorage.getItem('aide-theme');if(t)document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
</head>
<body class="{classe}">
<a class="evitement" href="#contenu">Aller au contenu</a>
<header class="barre">
  <button class="btn-icone seulement-mobile" id="ouvrir-nav" aria-label="Ouvrir le menu" aria-controls="nav" aria-expanded="false">{icone("menu")}</button>
  <a class="marque" href="{racine}index.html"><span class="logo" aria-hidden="true">SC</span><span>{esc(conf["nom_court"])}</span></a>
  <nav class="onglets" aria-label="Rubriques">{onglets}</nav>
  <button class="champ-recherche" id="ouvrir-recherche" type="button" aria-label="Rechercher dans l'aide">
    {icone("recherche")}<span>Rechercher…</span><kbd>/</kbd>
  </button>
  {lien_word}
  <button class="btn-icone" id="theme" type="button" aria-label="Changer de thème">{icone("lune", "ic ic-lune")}{icone("soleil", "ic ic-soleil")}</button>
</header>
<div class="cadre">
  <aside class="nav" id="nav" aria-label="Navigation">
    <nav class="onglets-mobile" aria-label="Rubriques">{onglets}</nav>
    {nav}
  </aside>
  <main id="contenu" tabindex="-1">
    {entete}
    <article class="page">
      {fil}
      {f'<h1>{esc(titre_page)}</h1>' if titre_page and page_url != "index.html" else ""}
      <div id="bandeau-parcours"></div>
      {contenu}
    </article>
    {pied_page}
    <footer class="pied">
      <p>{esc(conf["titre"])} · généré le {dt.date.today().strftime("%d/%m/%Y")}</p>
      <p><button type="button" class="lien-discret" onclick="window.print()">{icone("imprimer")} Imprimer cette page</button></p>
    </footer>
  </main>
  {f'<aside class="colonne-toc">{toc}</aside>' if toc else ""}
</div>
<div class="voile" id="voile" hidden></div>
<script src="{racine}assets/donnees.js"></script>
<script src="{racine}assets/app.js"></script>
</body>
</html>
"""


def page_accueil(conf, pages_par_md, corps_index, ancres):
    # l'encadré « Version Word » de docs/index.md est remplacé par le lien de la page d'accueil
    corps_index = re.sub(r'<div class="admonition[^"]*">\s*<p class="admonition-title">Version Word</p>.*?</div>', "", corps_index, count=1, flags=re.S)
    profils = []
    for p in conf["profils"]:
        etapes = [pages_par_md[m]["url"] for m in p["pages"] if m in pages_par_md]
        profils.append(
            f'<button type="button" class="carte-profil" data-profil="{p["id"]}" aria-pressed="false">'
            f'<span class="pastille">{icone(p["icone"])}</span>'
            f'<span class="profil-titre">{esc(p["titre"])}</span>'
            f'<span class="profil-resume">{esc(p["resume"])}</span>'
            f'<span class="profil-etapes">{len(etapes)} pages à lire</span></button>'
        )
    taches = []
    for libelle, md, titre_section in conf["taches"]:
        page = pages_par_md.get(md)
        if not page:
            avertir(f"tâche « {libelle} » : page {md} absente")
            continue
        ancre = next((a for (u, t, a) in ancres if u == page["url"] and sans_accents(titre_section) in sans_accents(t)), None)
        if ancre is None:
            avertir(f"tâche « {libelle} » : section « {titre_section} » introuvable dans {md}")
        cible = page["url"] + (f"#{ancre}" if ancre else "")
        taches.append(
            f'<li><a href="{cible}"><span class="tache-libelle">{esc(libelle)}</span>'
            f'<span class="tache-page">{esc(page["titre"])}</span>{icone("fleche")}</a></li>'
        )
    rubriques = []
    descriptions = {
        "guide": "Chaque écran expliqué pas à pas, avec captures : administration, portails formateur et étudiant, préinscription.",
        "installation": "Prérequis, mise en ligne, fichier .env, sauvegardes, mises à jour et dépannage du serveur.",
        "developpeurs": "Architecture, applications, permissions, tests et conventions pour faire évoluer le code.",
    }
    for cle, nom in SECTIONS.items():
        nb = sum(1 for p in pages_par_md.values() if p["rubrique"] == cle)
        rubriques.append(
            f'<a class="carte-rubrique" href="{cle}/index.html"><span class="rubrique-nom">{esc(nom)}</span>'
            f'<span class="rubrique-desc">{descriptions[cle]}</span><span class="rubrique-nb">{nb} pages {icone("fleche")}</span></a>'
        )
    suggestions = "".join(f'<button type="button" class="puce" data-recherche="{esc(s)}">{esc(s)}</button>' for s in conf["recherches_suggerees"])
    word = conf.get("fichier_word_url")
    return f"""
<section class="hero">
  <p class="surtitre">Plateforme SmartCampus</p>
  <h1>{esc(conf["titre"])}</h1>
  <p class="hero-texte">{esc(conf["sous_titre"])}. Choisissez votre profil ou posez votre question.</p>
  <form class="hero-recherche" id="hero-recherche" role="search">
    {icone("recherche")}
    <input type="search" id="hero-q" placeholder="Ex. : enregistrer un paiement" aria-label="Rechercher dans l'aide" autocomplete="off">
    <button type="submit" class="btn-principal">Rechercher</button>
  </form>
  <div class="puces" aria-label="Recherches fréquentes">{suggestions}</div>
</section>

<section class="bloc" aria-labelledby="titre-profils">
  <div class="bloc-entete"><h2 id="titre-profils">Je suis…</h2><p>Un parcours de lecture adapté à votre rôle. Votre progression est mémorisée sur cet appareil.</p></div>
  <div class="grille-profils">{''.join(profils)}</div>
  <div id="detail-parcours" class="detail-parcours" hidden></div>
</section>

<section class="bloc" aria-labelledby="titre-taches">
  <div class="bloc-entete"><h2 id="titre-taches">Comment faire pour…</h2><p>Les procédures les plus demandées, directement à la bonne section.</p></div>
  <ul class="grille-taches">{''.join(taches)}</ul>
</section>

<section class="bloc" aria-labelledby="titre-rubriques">
  <div class="bloc-entete"><h2 id="titre-rubriques">Toute la documentation</h2></div>
  <div class="grille-rubriques">{''.join(rubriques)}</div>
  {f'<p class="note-word">{icone("telecharger")} Toute la documentation existe aussi en un seul fichier : <a href="{word}" download>version Word</a>.</p>' if word else ""}
</section>

<section class="bloc contenu-accueil" aria-labelledby="titre-apropos">
  <div class="bloc-entete"><h2 id="titre-apropos">La plateforme en bref</h2></div>
  {corps_index}
</section>
"""


# --------------------------------------------------------------------------- principal


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
    for p in pages:
        corps, toc, titre = convertir_page(p["md"], (docs / p["md"]).read_text(encoding="utf-8"), sortie, diagrammes)
        p.update(corps=corps, toc=toc, titre=titre or p["titre_nav"] or p["md"])
        if not p["titre_nav"]:
            p["titre_nav"] = "Présentation" if p["md"].endswith("index.md") and p["md"] != "index.md" else p["titre"]
        rubrique_nom = SECTIONS.get(p["rubrique"], "Accueil")
        index_recherche += sections_pour_recherche(corps, p["titre"], p["url"], rubrique_nom)
        for m in re.finditer(r'<h[23] id="([^"]+)">(.*?)</h[23]>', corps, re.S):
            ancres.append((p["url"], texte_brut(re.sub(r'<a class="headerlink".*?</a>', "", m.group(2))), m.group(1)))

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
        nav = construire_nav_html(pages, p["url"], racine)
        if p["md"] == "index.md":
            contenu = page_accueil(conf, pages_par_md, p["corps"], ancres)
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
            miettes = [f'<a href="{racine}index.html">Accueil</a>']
            for g in p["groupes"]:
                idx = next((q for q in pages if q["groupes"][: len(miettes)] == p["groupes"][: len(miettes)] and q["groupes"] and q["groupes"][-1] == g and q["url"].endswith("index.html")), None)
                miettes.append(f'<a href="{racine}{idx["url"]}">{esc(g)}</a>' if idx and idx is not p else f"<span>{esc(g)}</span>")
            fil = f'<nav class="fil" aria-label="Fil d’Ariane">{SEPARATEUR.join(miettes)}</nav>'
            description = next((e["x"][:160] for e in index_recherche if e["u"] == p["url"]), "")
            html_page = gabarit(conf, titre_page=p["titre"], page_url=p["url"], contenu=p["corps"], nav=nav,
                                toc=toc_html(p["toc"]), fil=fil, pied_page=pied, description=description,
                                classe="page-glossaire" if p["md"].endswith("glossaire.md") else "")
        dest = sortie / p["url"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html_page, encoding="utf-8")

    # page 404 (serveurs web)
    (sortie / "404.html").write_text(gabarit(conf, titre_page="Page introuvable", page_url="404.html",
        contenu='<p>Cette page n\'existe pas ou a été déplacée.</p><p><a class="btn-principal" href="index.html">Retour à l\'accueil</a> '
                '<button type="button" class="btn-secondaire" data-ouvrir-recherche>Rechercher</button></p>',
        nav=construire_nav_html(pages, "404.html", "")), encoding="utf-8")
    print(f"{len(pages)} pages, {len(index_recherche)} entrées de recherche, {len(glossaire)} termes du glossaire, "
          f"{len(diagrammes)} diagrammes → {sortie / 'index.html'}")


if __name__ == "__main__":
    main()
