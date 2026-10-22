/* Centre d'aide SmartCampus — interactions (aucune dépendance) */
(function () {
  "use strict";
  var D = window.AIDE || { recherche: [], glossaire: [], parcours: {}, pages: [] };
  var racine = document.documentElement.dataset.racine || "";
  var pageCourante = document.documentElement.dataset.page || "";
  var $ = function (s, c) { return (c || document).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); };

  /* ---------------------------------------------------------------- stockage tolérant */
  var memoire = {};
  function lire(cle, defaut) {
    try { var v = localStorage.getItem("aide-" + cle); return v === null ? defaut : JSON.parse(v); }
    catch (e) { return cle in memoire ? memoire[cle] : defaut; }
  }
  function ecrire(cle, valeur) {
    memoire[cle] = valeur;
    try { localStorage.setItem("aide-" + cle, JSON.stringify(valeur)); } catch (e) { /* navigation privée */ }
  }

  /* ---------------------------------------------------------------- texte */
  // minuscules sans accents, longueur conservée (index identiques à l'original)
  function norm(t) {
    var r = "";
    for (var i = 0; i < t.length; i++) {
      var c = t[i].normalize ? t[i].normalize("NFD")[0] : t[i];
      r += c.toLowerCase().length === 1 ? c.toLowerCase() : t[i];
    }
    return r;
  }
  function echapper(t) {
    return String(t).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; });
  }
  var MOTS_VIDES = "le la les l de des du d un une et ou a au aux en je j me mon ma mes on il elle ce cet cette ces se sa son ses que qu qui quoi comment pourquoi quand faire fait pour par sur dans avec est sont y t vous nous puis peut".split(" ");
  function mots(q) {
    return norm(q).split(/[^a-z0-9œæ]+/).filter(function (m) { return m && MOTS_VIDES.indexOf(m) < 0; });
  }
  function racineMot(m) { return m.length > 4 ? m.replace(/(es|s|x)$/, "") : m; }

  /* ---------------------------------------------------------------- thème */
  var btnTheme = $("#theme");
  function themeEffectif() {
    var t = document.documentElement.dataset.theme;
    if (t) return t;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function majLibelleTheme() {
    if (btnTheme) btnTheme.setAttribute("aria-label", themeEffectif() === "dark" ? "Passer en mode clair" : "Passer en mode sombre");
  }
  if (btnTheme) {
    majLibelleTheme();
    btnTheme.addEventListener("click", function () {
      var t = themeEffectif() === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = t;
      try { localStorage.setItem("aide-theme", t); } catch (e) { }
      majLibelleTheme();
    });
  }

  /* ---------------------------------------------------------------- menu mobile */
  var nav = $("#nav"), voile = $("#voile"), btnNav = $("#ouvrir-nav");
  function fermerNav() {
    if (!nav) return;
    nav.classList.remove("ouverte"); if (voile) voile.hidden = true;
    if (btnNav) btnNav.setAttribute("aria-expanded", "false");
  }
  if (btnNav && nav) {
    btnNav.addEventListener("click", function () {
      nav.classList.add("ouverte"); voile.hidden = false; btnNav.setAttribute("aria-expanded", "true");
      var c = $('a[aria-current="page"]', nav) || $("a", nav); if (c) c.focus();
    });
    voile.addEventListener("click", fermerNav);
  }
  var courant = nav && $('a[aria-current="page"]', nav);
  if (courant && courant.scrollIntoView) { courant.scrollIntoView({ block: "center" }); window.scrollTo(0, 0); }

  /* ---------------------------------------------------------------- pages consultées */
  var lues = lire("lues", []);
  if (pageCourante && pageCourante !== "index.html" && lues.indexOf(pageCourante) < 0) { lues.push(pageCourante); ecrire("lues", lues); }
  $$(".nav-arbre a[data-page], .parcours-coches a[data-page]").forEach(function (a) { if (lues.indexOf(a.dataset.page) >= 0) { a.classList.add("lu"); a.title = "Déjà consultée"; } });

  /* ---------------------------------------------------------------- recherche */
  var INDEX = D.recherche.map(function (e) {
    return { e: e, s: norm(e.s || ""), p: norm(e.p || ""), x: norm(e.x || "") };
  });
  var modale = null, champ, liste, filtreRubrique = "", selection = -1, resultatsCourants = [];

  function chercher(q) {
    var ms = mots(q);
    if (!ms.length) return [];
    var res = [];
    for (var i = 0; i < INDEX.length; i++) {
      var it = INDEX[i], score = 0, ok = true;
      if (filtreRubrique && it.e.r !== filtreRubrique) continue;
      for (var j = 0; j < ms.length; j++) {
        var m = racineMot(ms[j]), s = 0;
        var ds = it.s.indexOf(m), dp = it.p.indexOf(m), dx = it.x.indexOf(m);
        if (ds >= 0) s += 12 + (ds === 0 || /[^a-z0-9]/.test(it.s[ds - 1]) ? 6 : 0);
        if (dp >= 0) s += 6;
        if (dx >= 0) {
          var n = 0, k = dx; while (k >= 0 && n < 6) { n++; k = it.x.indexOf(m, k + m.length); }
          s += 2 + n * 0.6;
        }
        if (!s) { ok = false; break; }
        score += s;
      }
      if (!ok) continue;
      if (it.e.q) score += 4;
      if (ms.length > 1 && it.x.indexOf(ms.map(racineMot).join(" ")) >= 0) score += 8;
      res.push({ it: it, score: score });
    }
    res.sort(function (a, b) { return b.score - a.score; });
    return res.slice(0, 40);
  }

  function surligner(texte, ms) {
    var n = norm(texte), plages = [];
    ms.forEach(function (m) {
      m = racineMot(m); if (m.length < 2) return;
      var k = n.indexOf(m);
      while (k >= 0) { plages.push([k, k + m.length]); k = n.indexOf(m, k + m.length); }
    });
    if (!plages.length) return echapper(texte);
    plages.sort(function (a, b) { return a[0] - b[0]; });
    var out = "", pos = 0;
    plages.forEach(function (p) {
      if (p[0] < pos) return;
      out += echapper(texte.slice(pos, p[0])) + "<mark>" + echapper(texte.slice(p[0], p[1])) + "</mark>"; pos = p[1];
    });
    return out + echapper(texte.slice(pos));
  }

  function extrait(it, ms) {
    var x = it.e.x || "", premier = -1;
    ms.forEach(function (m) { var k = it.x.indexOf(racineMot(m)); if (k >= 0 && (premier < 0 || k < premier)) premier = k; });
    var debut = Math.max(0, premier - 60);
    var bout = x.slice(debut, debut + 220);
    return (debut > 0 ? "… " : "") + bout + (debut + 220 < x.length ? " …" : "");
  }

  function afficherResultats() {
    var q = champ.value.trim();
    var ms = mots(q);
    resultatsCourants = chercher(q);
    selection = resultatsCourants.length ? 0 : -1;
    if (!q) {
      liste.innerHTML = '<li class="vide">Tapez un mot-clé : <em>paiement</em>, <em>notes</em>, <em>mot de passe</em>, <em>congé</em>…</li>';
      return;
    }
    if (!resultatsCourants.length) {
      liste.innerHTML = '<li class="vide">Aucun résultat pour « ' + echapper(q) + ' ».<br>Essayez un autre mot, ou consultez la <a href="' + racine + 'guide/faq.html">FAQ</a> et le <a href="' + racine + 'guide/glossaire.html">glossaire</a>.</li>';
      return;
    }
    liste.innerHTML = resultatsCourants.map(function (r, i) {
      var e = r.it.e;
      var titre = e.s || e.p;
      return '<li><a href="' + racine + e.u + '" data-i="' + i + '" role="option" aria-selected="' + (i === 0) + '">' +
        '<span class="r-chemin">' + echapper(e.r) + " › " + echapper(e.p) + "</span>" +
        '<span class="r-titre">' + (e.q ? '<span class="r-badge">FAQ</span>' : "") + surligner(titre, ms) + "</span>" +
        '<span class="r-extrait">' + surligner(extrait(r.it, ms), ms) + "</span></a></li>";
    }).join("");
  }

  function choisir(i) {
    var liens = $$("a[data-i]", liste);
    liens.forEach(function (a, k) { a.setAttribute("aria-selected", String(k === i)); });
    selection = i;
    if (liens[i]) liens[i].scrollIntoView({ block: "nearest" });
  }

  function ouvrirRecherche(q) {
    if (!modale) {
      modale = document.createElement("div");
      modale.className = "recherche-modale"; modale.hidden = true;
      modale.setAttribute("role", "dialog"); modale.setAttribute("aria-modal", "true"); modale.setAttribute("aria-label", "Rechercher dans l'aide");
      var rubriques = [];
      D.recherche.forEach(function (e) { if (rubriques.indexOf(e.r) < 0) rubriques.push(e.r); });
      modale.innerHTML =
        '<div class="recherche-boite">' +
        '<div class="recherche-saisie"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>' +
        '<input type="search" placeholder="Rechercher une procédure, un écran, un message d\'erreur…" autocomplete="off" aria-controls="resultats-recherche">' +
        '<button type="button" class="btn-icone" data-fermer aria-label="Fermer la recherche"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button></div>' +
        '<div class="recherche-filtres" role="group" aria-label="Limiter à une rubrique"><button type="button" data-r="" aria-pressed="true">Tout</button>' +
        rubriques.map(function (r) { return '<button type="button" data-r="' + echapper(r) + '" aria-pressed="false">' + echapper(r) + "</button>"; }).join("") + "</div>" +
        '<ul class="resultats" id="resultats-recherche" role="listbox" aria-label="Résultats"></ul>' +
        '<div class="recherche-aide"><span><kbd>↑</kbd> <kbd>↓</kbd> naviguer</span><span><kbd>Entrée</kbd> ouvrir</span><span><kbd>Échap</kbd> fermer</span></div></div>';
      document.body.appendChild(modale);
      champ = $("input", modale); liste = $(".resultats", modale);
      champ.addEventListener("input", afficherResultats);
      champ.addEventListener("keydown", function (ev) {
        var n = resultatsCourants.length;
        if (ev.key === "ArrowDown") { ev.preventDefault(); if (n) choisir((selection + 1) % n); }
        else if (ev.key === "ArrowUp") { ev.preventDefault(); if (n) choisir((selection - 1 + n) % n); }
        else if (ev.key === "Enter") { var a = $('a[data-i="' + selection + '"]', liste); if (a) { ev.preventDefault(); a.click(); } }
      });
      liste.addEventListener("click", function (ev) {
        var a = ev.target.closest("a[data-i]"); if (!a) return;
        try { sessionStorage.setItem("aide-surligner", champ.value.trim()); } catch (e) { }
        fermerRecherche(); // si l'ancre est sur la même page
        if (a.pathname === location.pathname) setTimeout(function () { surlignerPage(); ouvrirAncre(); }, 30);
      });
      modale.addEventListener("click", function (ev) {
        if (ev.target === modale || ev.target.closest("[data-fermer]")) fermerRecherche();
        var f = ev.target.closest("[data-r]");
        if (f) {
          filtreRubrique = f.dataset.r;
          $$("[data-r]", modale).forEach(function (b) { b.setAttribute("aria-pressed", String(b === f)); });
          afficherResultats(); champ.focus();
        }
      });
    }
    modale.hidden = false;
    document.body.style.overflow = "hidden";
    champ.value = q || champ.value || "";
    afficherResultats();
    champ.focus(); champ.select();
  }
  function fermerRecherche() {
    if (!modale || modale.hidden) return;
    modale.hidden = true; document.body.style.overflow = "";
    var b = $("#ouvrir-recherche"); if (b) b.focus({ preventScroll: true });
  }
  var btnRecherche = $("#ouvrir-recherche");
  if (btnRecherche) btnRecherche.addEventListener("click", function () { ouvrirRecherche(); });
  $$("[data-ouvrir-recherche]").forEach(function (b) { b.addEventListener("click", function () { ouvrirRecherche(); }); });
  var hero = $("#hero-recherche");
  if (hero) hero.addEventListener("submit", function (ev) { ev.preventDefault(); ouvrirRecherche($("#hero-q").value); });
  $$("[data-recherche]").forEach(function (b) { b.addEventListener("click", function () { ouvrirRecherche(b.dataset.recherche); }); });

  document.addEventListener("keydown", function (ev) {
    var dansChamp = /INPUT|TEXTAREA|SELECT/.test((ev.target.tagName || "")) || ev.target.isContentEditable;
    if ((ev.key === "k" || ev.key === "K") && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); ouvrirRecherche(); }
    else if (ev.key === "/" && !dansChamp) { ev.preventDefault(); ouvrirRecherche(); }
    else if (ev.key === "Escape") { fermerRecherche(); fermerNav(); fermerVisionneuse(); }
  });

  /* surlignage des mots recherchés sur la page d'arrivée */
  function surlignerPage() {
    var q = "";
    try { q = sessionStorage.getItem("aide-surligner") || ""; sessionStorage.removeItem("aide-surligner"); } catch (e) { }
    var ms = mots(q).map(racineMot).filter(function (m) { return m.length >= 3; });
    var page = $(".page");
    if (!ms.length || !page) return;
    $$("mark.surligne", page).forEach(function (m) { m.replaceWith(document.createTextNode(m.textContent)); });
    var marcheur = document.createTreeWalker(page, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        return n.parentElement.closest("script,style,.fil,.bandeau-recherche,.headerlink,kbd") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      }
    });
    var noeuds = [], n, total = 0;
    while ((n = marcheur.nextNode())) noeuds.push(n);
    noeuds.forEach(function (noeud) {
      var t = noeud.nodeValue, nt = norm(t), plages = [];
      ms.forEach(function (m) { var k = nt.indexOf(m); while (k >= 0) { plages.push([k, k + m.length]); k = nt.indexOf(m, k + m.length); } });
      if (!plages.length) return;
      plages.sort(function (a, b) { return a[0] - b[0]; });
      var frag = document.createDocumentFragment(), pos = 0;
      plages.forEach(function (p) {
        if (p[0] < pos) return;
        frag.appendChild(document.createTextNode(t.slice(pos, p[0])));
        var mk = document.createElement("mark"); mk.className = "surligne"; mk.textContent = t.slice(p[0], p[1]);
        frag.appendChild(mk); pos = p[1]; total++;
      });
      frag.appendChild(document.createTextNode(t.slice(pos)));
      noeud.parentNode.replaceChild(frag, noeud);
    });
    if (!total) return;
    var vieux = $(".bandeau-recherche"); if (vieux) vieux.remove();
    var b = document.createElement("div");
    b.className = "bandeau-recherche";
    b.innerHTML = "<span>" + total + " occurrence" + (total > 1 ? "s" : "") + " de « " + echapper(q) + " » surlignée" + (total > 1 ? "s" : "") + '.</span> <button type="button" class="lien-discret">Effacer</button>';
    $("button", b).addEventListener("click", function () {
      $$("mark.surligne", page).forEach(function (m) { m.replaceWith(document.createTextNode(m.textContent)); });
      b.remove();
    });
    var h1 = $("h1", page);
    if (h1) h1.insertAdjacentElement("afterend", b); else page.prepend(b);
    if (!location.hash) { var premiere = $("mark.surligne", page); if (premiere) premiere.scrollIntoView({ block: "center" }); }
  }

  /* ---------------------------------------------------------------- ancres dans des blocs repliés */
  function ouvrirAncre() {
    if (!location.hash) return;
    var cible = null;
    try { cible = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch (e) { }
    if (!cible) return;
    var d = cible.closest("details"); while (d) { d.open = true; d = d.parentElement && d.parentElement.closest("details"); }
    cible.scrollIntoView();
  }
  window.addEventListener("hashchange", ouvrirAncre);

  /* ---------------------------------------------------------------- copier le code */
  $$(".page .highlight").forEach(function (bloc) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "copier"; b.textContent = "Copier";
    b.addEventListener("click", function () {
      var code = $("code", bloc) || bloc;
      var texte = code.innerText.replace(/\n$/, "");
      var fini = function () { b.textContent = "Copié ✓"; b.classList.add("ok"); setTimeout(function () { b.textContent = "Copier"; b.classList.remove("ok"); }, 1600); };
      if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(texte).then(fini, function () { copieSecours(texte); fini(); });
      else { copieSecours(texte); fini(); }
    });
    bloc.appendChild(b);
  });
  function copieSecours(t) {
    var z = document.createElement("textarea"); z.value = t; z.style.position = "fixed"; z.style.opacity = "0";
    document.body.appendChild(z); z.select(); try { document.execCommand("copy"); } catch (e) { } z.remove();
  }

  /* ---------------------------------------------------------------- sommaire actif */
  var liensToc = $$(".toc a");
  if (liensToc.length && "IntersectionObserver" in window) {
    var titres = liensToc.map(function (a) { return document.getElementById(decodeURIComponent(a.hash.slice(1))); }).filter(Boolean);
    var visibles = new Set();
    var obs = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (e) { if (e.isIntersecting) visibles.add(e.target); else visibles.delete(e.target); });
      var actif = null;
      for (var i = 0; i < titres.length; i++) { if (visibles.has(titres[i])) { actif = titres[i]; break; } }
      if (!actif) { // titre le plus proche au-dessus
        for (var j = titres.length - 1; j >= 0; j--) { if (titres[j].getBoundingClientRect().top < 120) { actif = titres[j]; break; } }
      }
      liensToc.forEach(function (a) { a.classList.toggle("actif", !!actif && a.hash.slice(1) === actif.id); });
    }, { rootMargin: "-70px 0px -60% 0px" });
    titres.forEach(function (t) { obs.observe(t); });
  }

  /* ---------------------------------------------------------------- visionneuse de captures */
  var vis = null, imagesPage = [], indexVis = 0;
  function majVisionneuse() {
    var im = imagesPage[indexVis];
    $(".vis-scene img", vis).src = im.currentSrc || im.src;
    $(".vis-scene img", vis).alt = im.alt;
    $(".vis-titre", vis).textContent = im.alt || "Capture d'écran";
    $(".vis-compteur", vis).textContent = (indexVis + 1) + " / " + imagesPage.length;
    $(".vis-scene", vis).classList.remove("zoom");
    $$(".vis-nav", vis).forEach(function (b) { b.hidden = imagesPage.length < 2; });
  }
  function ouvrirVisionneuse(i) {
    if (!vis) {
      vis = document.createElement("div");
      vis.className = "visionneuse"; vis.setAttribute("role", "dialog"); vis.setAttribute("aria-modal", "true"); vis.setAttribute("aria-label", "Capture d'écran agrandie");
      var svg = function (d) { return '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + d + "</svg>"; };
      vis.innerHTML = '<div class="vis-barre"><p class="vis-titre"></p><span class="vis-compteur"></span>' +
        '<button type="button" class="vis-nav" data-dir="-1" aria-label="Capture précédente">' + svg('<path d="m15 18-6-6 6-6"/>') + "</button>" +
        '<button type="button" class="vis-nav" data-dir="1" aria-label="Capture suivante">' + svg('<path d="m9 18 6-6-6-6"/>') + "</button>" +
        '<button type="button" data-zoom aria-label="Taille réelle">' + svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M11 8v6M8 11h6"/>') + "</button>" +
        '<button type="button" data-fermer aria-label="Fermer">' + svg('<path d="M18 6 6 18M6 6l12 12"/>') + "</button></div>" +
        '<div class="vis-scene"><img alt=""></div>';
      document.body.appendChild(vis);
      vis.addEventListener("click", function (ev) {
        var nav = ev.target.closest(".vis-nav");
        if (nav) { indexVis = (indexVis + Number(nav.dataset.dir) + imagesPage.length) % imagesPage.length; majVisionneuse(); return; }
        if (ev.target.closest("[data-fermer]") || ev.target.classList.contains("vis-scene")) { fermerVisionneuse(); return; }
        if (ev.target.closest("[data-zoom]") || ev.target.tagName === "IMG") $(".vis-scene", vis).classList.toggle("zoom");
      });
      vis.addEventListener("keydown", function (ev) {
        if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
          indexVis = (indexVis + (ev.key === "ArrowRight" ? 1 : -1) + imagesPage.length) % imagesPage.length; majVisionneuse();
        }
      });
    }
    indexVis = i; vis.hidden = false; document.body.style.overflow = "hidden";
    majVisionneuse(); $("[data-fermer]", vis).focus();
  }
  function fermerVisionneuse() {
    if (!vis || vis.hidden) return;
    vis.hidden = true; document.body.style.overflow = "";
    var b = imagesPage[indexVis] && imagesPage[indexVis].closest("button"); if (b) b.focus({ preventScroll: true });
  }
  $$(".capture .zoom").forEach(function (b, i) {
    imagesPage.push($("img", b));
    b.addEventListener("click", function () { ouvrirVisionneuse(i); });
  });

  /* ---------------------------------------------------------------- listes à cocher mémorisées */
  $$(".page ul.task-list").forEach(function (ul, n) {
    if (ul.parentElement.closest("ul.task-list")) return;
    var cle = "coches:" + pageCourante + ":" + n;
    var etat = lire(cle, {});
    var cases = $$('input[type="checkbox"]', ul);
    var barre = document.createElement("div");
    barre.className = "progression-liste";
    barre.innerHTML = '<span class="pl-texte"></span><div class="jauge"><span></span></div><button type="button" class="lien-discret">Tout décocher</button>';
    ul.insertAdjacentElement("beforebegin", barre);
    function maj() {
      var faits = cases.filter(function (c) { return c.checked; }).length;
      $(".pl-texte", barre).textContent = faits + " / " + cases.length + " fait" + (faits > 1 ? "s" : "");
      $(".jauge span", barre).style.width = (cases.length ? 100 * faits / cases.length : 0) + "%";
      cases.forEach(function (c) { c.closest("li").classList.toggle("fait", c.checked); });
    }
    cases.forEach(function (c, i) {
      if (i in etat) c.checked = !!etat[i];
      var li = c.closest("li");
      c.setAttribute("aria-label", (li.textContent || "").trim().slice(0, 120));
      c.addEventListener("change", function () { etat[i] = c.checked; ecrire(cle, etat); maj(); });
    });
    $("button", barre).addEventListener("click", function () { cases.forEach(function (c) { c.checked = false; }); etat = {}; ecrire(cle, etat); maj(); });
    maj();
  });

  /* ---------------------------------------------------------------- blocs repliables : tout déplier */
  var blocs = $$(".page > details, .page > .admonition + details");
  if (blocs.length >= 4) {
    var outil = document.createElement("p");
    outil.innerHTML = '<button type="button" class="btn-secondaire petit">Tout déplier</button>';
    var bt = $("button", outil), ouvert = false;
    bt.addEventListener("click", function () {
      ouvert = !ouvert; $$(".page details").forEach(function (d) { d.open = ouvert; });
      bt.textContent = ouvert ? "Tout replier" : "Tout déplier";
    });
    var avant = $(".page .meta-article") || $(".page h1"); if (avant) avant.insertAdjacentElement("afterend", outil);
  }

  /* ---------------------------------------------------------------- glossaire */
  function slug(t) { return norm(t).replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); }
  var urlGlossaire = "guide/glossaire.html";
  if (document.body.classList.contains("page-glossaire")) {
    var dts = $$(".page dl dt");
    dts.forEach(function (dt) { dt.id = slug(dt.textContent); });
    var dl = $(".page dl");
    if (dl) {
      var lettres = [];
      dts.forEach(function (dt) { var l = norm(dt.textContent.trim()[0] || "").toUpperCase(); if (lettres.indexOf(l) < 0) { lettres.push(l); dt.dataset.lettre = l; } });
      var filtre = document.createElement("div");
      filtre.innerHTML = '<input type="search" class="filtre-glossaire" placeholder="Filtrer les ' + dts.length + ' termes…" aria-label="Filtrer le glossaire">' +
        '<nav class="alphabet" aria-label="Aller à la lettre">' + lettres.map(function (l) {
          var dt = dts.filter(function (d) { return d.dataset.lettre === l; })[0];
          return '<a href="#' + dt.id + '">' + l + "</a>";
        }).join("") + "</nav>";
      dl.insertAdjacentElement("beforebegin", filtre);
      $("input", filtre).addEventListener("input", function () {
        var m = norm(this.value.trim());
        dts.forEach(function (dt) {
          var dd = dt.nextElementSibling, ok = !m || norm(dt.textContent + " " + (dd ? dd.textContent : "")).indexOf(m) >= 0;
          dt.hidden = !ok; if (dd) dd.hidden = !ok;
        });
      });
    }
    ouvrirAncre();
  } else if (D.glossaire.length && /^guide\//.test(pageCourante)) {
    var bulle = null;
    var deja = {};
    var zones = $$(".page p, .page li, .page td, .page dd");
    D.glossaire.forEach(function (g) {
      var cle = g.c;
      if (cle.length < 2) return;
      var sensible = cle === cle.toUpperCase();
      var motif;
      try { motif = new RegExp("(^|[^\\p{L}\\p{N}])(" + cle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")(?=$|[^\\p{L}\\p{N}])", sensible ? "u" : "iu"); }
      catch (e) { return; }
      for (var z = 0; z < zones.length && !deja[cle]; z++) {
        var mar = document.createTreeWalker(zones[z], NodeFilter.SHOW_TEXT, {
          acceptNode: function (n) { return n.parentElement.closest("a,code,kbd,strong,h1,h2,h3,h4,summary,.admonition-title,.terme,figcaption") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; }
        });
        var nd;
        while ((nd = mar.nextNode())) {
          var m = motif.exec(nd.nodeValue);
          if (!m) continue;
          var debut = m.index + m[1].length;
          var suite = nd.splitText(debut); suite.splitText(m[2].length);
          var a = document.createElement("a");
          a.className = "terme"; a.href = racine + urlGlossaire + "#" + slug(g.t);
          a.dataset.terme = g.t; a.dataset.def = g.d; a.textContent = suite.nodeValue;
          a.setAttribute("aria-describedby", "infobulle");
          suite.parentNode.replaceChild(a, suite);
          deja[cle] = true; break;
        }
      }
    });
    var montrer = function (ev) {
      var a = ev.target.closest && ev.target.closest(".terme"); if (!a) return;
      if (!bulle) { bulle = document.createElement("div"); bulle.className = "infobulle"; bulle.id = "infobulle"; bulle.setAttribute("role", "tooltip"); document.body.appendChild(bulle); }
      bulle.innerHTML = "<strong>" + echapper(a.dataset.terme) + "</strong>" + echapper(a.dataset.def);
      bulle.hidden = false;
      var r = a.getBoundingClientRect(), l = Math.min(window.innerWidth - bulle.offsetWidth - 12, Math.max(12, r.left));
      var haut = r.top + window.scrollY - bulle.offsetHeight - 8;
      if (r.top - bulle.offsetHeight - 8 < 70) haut = r.bottom + window.scrollY + 8;
      bulle.style.left = l + "px"; bulle.style.top = haut + "px";
    };
    var cacher = function (ev) { if (bulle && ev.target.closest && ev.target.closest(".terme")) bulle.hidden = true; };
    document.addEventListener("mouseover", montrer); document.addEventListener("focusin", montrer);
    document.addEventListener("mouseout", cacher); document.addEventListener("focusout", cacher);
  }

  /* ---------------------------------------------------------------- parcours par profil */
  function progression(id) {
    var p = D.parcours[id]; if (!p) return { faits: 0, total: 0 };
    var f = p.pages.filter(function (e) { return lues.indexOf(e.u) >= 0; }).length;
    return { faits: f, total: p.pages.length };
  }
  var grille = $(".grille-profils");
  if (grille) {
    var detail = $("#detail-parcours");
    var cartes = $$(".carte-profil", grille);
    cartes.forEach(function (c) {
      var pr = progression(c.dataset.profil);
      if (pr.faits) {
        var j = document.createElement("span"); j.className = "jauge"; j.innerHTML = '<span style="width:' + (100 * pr.faits / pr.total) + '%"></span>';
        c.appendChild(j);
        $(".profil-etapes", c).textContent = pr.faits + " / " + pr.total + " pages consultées";
      }
    });
    var montrerParcours = function (id, defiler) {
      var p = D.parcours[id]; if (!p) return;
      ecrire("profil", id);
      cartes.forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset.profil === id)); });
      var pr = progression(id);
      var prochaine = p.pages.filter(function (e) { return lues.indexOf(e.u) < 0; })[0] || p.pages[0];
      detail.innerHTML = '<h3>Parcours « ' + echapper(p.titre) + ' »</h3>' +
        '<p class="dp-sous">' + (pr.faits === pr.total ? "Parcours terminé : vous avez consulté toutes les pages." : pr.faits + " page" + (pr.faits > 1 ? "s" : "") + " consultée" + (pr.faits > 1 ? "s" : "") + " sur " + pr.total + ". Lisez-les dans l'ordre.") + "</p>" +
        '<div class="jauge" style="margin-bottom:16px"><span style="width:' + (100 * pr.faits / Math.max(1, pr.total)) + '%"></span></div>' +
        '<ol class="etapes">' + p.pages.map(function (e) {
          var lu = lues.indexOf(e.u) >= 0;
          return '<li class="' + (lu ? "lu" : "") + '"><a href="' + racine + e.u + '">' + echapper(e.t) + '<span class="etat">' + (lu ? "Consultée" : "") + "</span></a></li>";
        }).join("") + "</ol>" +
        '<div class="dp-actions"><a class="btn-principal" href="' + racine + prochaine.u + '">' + (pr.faits ? "Continuer" : "Commencer") + ' le parcours <svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></a>' +
        (pr.faits ? '<button type="button" class="lien-discret" data-raz>Remettre la progression à zéro</button>' : "") + "</div>";
      detail.hidden = false;
      var raz = $("[data-raz]", detail);
      if (raz) raz.addEventListener("click", function () {
        lues = lues.filter(function (u) { return !p.pages.some(function (e) { return e.u === u; }); });
        ecrire("lues", lues); location.reload();
      });
      if (defiler) detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
    };
    cartes.forEach(function (c) { c.addEventListener("click", function () { montrerParcours(c.dataset.profil, true); }); });
    var demande = (location.search.match(/[?&]profil=([\w-]+)/) || [])[1];
    if (demande && D.parcours[demande]) ecrire("profil", demande);
    var choisi = lire("profil", null);
    if (choisi && D.parcours[choisi]) montrerParcours(choisi, false);
  }

  var bandeau = $("#bandeau-parcours");
  var profil = lire("profil", null);
  if (bandeau && profil && D.parcours[profil]) {
    var pc = D.parcours[profil];
    var rang = -1;
    pc.pages.forEach(function (e, i) { if (e.u === pageCourante) rang = i; });
    if (rang >= 0) {
      var suivante = pc.pages[rang + 1];
      var prg = progression(profil);
      bandeau.innerHTML = '<div class="bandeau-parcours"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="6" cy="19" r="2.5"/><circle cx="18" cy="5" r="2.5"/><path d="M8.5 19H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5"/></svg>' +
        '<div class="bp-texte"><strong>Parcours « ' + echapper(pc.titre) + " »</strong> — étape " + (rang + 1) + " sur " + pc.pages.length +
        '<div class="jauge" style="margin-top:6px;max-width:260px"><span style="width:' + (100 * prg.faits / pc.pages.length) + '%"></span></div></div>' +
        '<div class="bp-actions">' + (suivante ? '<a class="btn-principal petit" href="' + racine + suivante.u + '">Étape suivante : ' + echapper(suivante.t) + "</a>" : '<a class="btn-secondaire petit" href="' + racine + 'index.html#titre-profils">Parcours terminé ✓</a>') +
        '<a class="btn-secondaire petit" href="' + racine + 'index.html#titre-profils">Changer de profil</a></div></div>';
    }
  }

  /* ---------------------------------------------------------------- avis « Cet article vous a-t-il été utile ? » */
  var avis = $(".avis");
  if (avis) {
    var cleAvis = "avis:" + pageCourante;
    var merci = function (v) {
      $$("[data-avis]", avis).forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.avis === v)); });
      var m = $(".avis-merci", avis);
      if (!m) { m = document.createElement("p"); m.className = "avis-merci"; m.setAttribute("role", "status"); $(".avis-boutons", avis).insertAdjacentElement("beforebegin", m); }
      m.textContent = v === "oui" ? "Merci pour votre retour !" : "Merci. Consultez la FAQ ou contactez le support si besoin.";
    };
    var dejaAvis = lire(cleAvis, null);
    if (dejaAvis) merci(dejaAvis);
    $$("[data-avis]", avis).forEach(function (b) {
      b.addEventListener("click", function () { ecrire(cleAvis, b.dataset.avis); merci(b.dataset.avis); });
    });
  }

  /* ---------------------------------------------------------------- remonter */
  var haut = document.createElement("button");
  haut.type = "button"; haut.className = "remonter"; haut.setAttribute("aria-label", "Revenir en haut de la page");
  haut.innerHTML = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 19V5M6 11l6-6 6 6"/></svg>';
  haut.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: "smooth" }); });
  document.body.appendChild(haut);
  var visibleHaut = false;
  window.addEventListener("scroll", function () {
    var v = window.scrollY > 700;
    if (v !== visibleHaut) { visibleHaut = v; haut.classList.toggle("visible", v); }
  }, { passive: true });

  surlignerPage();
  ouvrirAncre();
})();
