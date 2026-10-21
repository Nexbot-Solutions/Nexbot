/*
 * Widget NexBot — à coller sur le site du client :
 *
 *   <script src="https://TON-SERVEUR/widget.js" data-client="ID_DU_CLIENT" async></script>
 *
 * Couleur : celle du champ "couleur" du fichier clients/ID_DU_CLIENT.json
 * (ex. "#0a7d5a"). Pour la tester sans toucher au serveur, on peut aussi
 * ajouter data-couleur="#0a7d5a" sur la balise <script>.
 * Avec la valeur "auto" (data-couleur="auto" ou "couleur": "auto"), le widget
 * prend la couleur principale du site du client.
 */
(function () {
  var script = document.currentScript || document.querySelector('script[src*="widget.js"]');
  if (!script) return;
  var idClient = script.getAttribute("data-client");
  if (!idClient) return console.error("widget.js : attribut data-client manquant");
  var base = new URL(script.src, window.location.href).origin;
  var cleSession = "bot_session_" + idClient;
  var LOGO = base + "/static/IMG_7106.jpeg";

  function lire(cle) { try { return localStorage.getItem(cle); } catch (e) { return null; } }
  function ecrire(cle, val) { try { localStorage.setItem(cle, val); } catch (e) {} }

  // --- Couleurs ---
  var VIOLET_NEXBOT = "#8b5cf6";
  function hexValide(h) { return /^#[0-9a-f]{6}$/i.test(h || ""); }
  function rgb(h) { return [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]; }
  function hex(a) {
    return "#" + a.map(function (v) {
      v = Math.max(0, Math.min(255, Math.round(v)));
      return (v < 16 ? "0" : "") + v.toString(16);
    }).join("");
  }
  function melange(h1, h2, t) {
    var a = rgb(h1), b = rgb(h2);
    return hex([0, 1, 2].map(function (i) { return a[i] + (b[i] - a[i]) * t; }));
  }
  function rgba(h, alpha) { var c = rgb(h); return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + alpha + ")"; }
  function luminosite(h) { var c = rgb(h); return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255; }

  // Détection automatique de la couleur du site (quand couleur = "auto") :
  // 1) la balise <meta name="theme-color">, 2) la couleur la plus vive parmi
  // les boutons et liens de la page. Sinon : mauve NexBot.
  function versHex(valeur) {
    var m = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)/.exec(valeur || "");
    return m ? hex([+m[1], +m[2], +m[3]]) : null;
  }
  function vivacite(h) { var c = rgb(h); return Math.max(c[0], c[1], c[2]) - Math.min(c[0], c[1], c[2]); }
  function detecterCouleurSite() {
    try {
      var meta = document.querySelector('meta[name="theme-color"]');
      var mc = meta && meta.getAttribute("content");
      if (hexValide(mc) && vivacite(mc) > 40) return mc;
      var meilleure = null, score = 40;
      var cibles = document.querySelectorAll('button, [class*="btn"], [class*="button"], input[type="submit"], a');
      for (var i = 0; i < cibles.length && i < 80; i++) {
        var s = getComputedStyle(cibles[i]);
        var cands = [versHex(s.backgroundColor), cibles[i].tagName === "A" ? versHex(s.color) : null];
        for (var j = 0; j < cands.length; j++) {
          if (cands[j] && vivacite(cands[j]) > score) { score = vivacite(cands[j]); meilleure = cands[j]; }
        }
      }
      return meilleure || VIOLET_NEXBOT;
    } catch (e) { return VIOLET_NEXBOT; }
  }

  // Palette complète du widget à partir d'une seule couleur d'accent.
  // Le mauve NexBot garde exactement les teintes d'origine.
  function palette(couleur) {
    if (!hexValide(couleur)) couleur = VIOLET_NEXBOT;
    couleur = couleur.toLowerCase();
    if (couleur === VIOLET_NEXBOT) {
      return { c: couleur, haut: "#9a6dff", haut2: "#a47bff", bas: "#5b2fd6", clair: "#bda4ff",
               fond: "#07050d", ent1: "#1a1033", ent2: "#120c22", bord: "#2a1f47", bot: "#1d1433",
               muet: "#a99fc4", ph: "#7d7399", texte: "#f3f0fa", sur: "#fff" };
    }
    // Une couleur très foncée serait invisible sur le fond sombre : on l'éclaircit un peu.
    if (luminosite(couleur) < 0.2) couleur = melange(couleur, "#ffffff", 0.35);
    var claire = luminosite(couleur) > 0.68;
    var noir = "#050505";
    return {
      c: couleur,
      haut: melange(couleur, "#ffffff", 0.12),
      haut2: melange(couleur, "#ffffff", 0.18),
      bas: claire ? couleur : melange(couleur, "#000000", 0.38),
      clair: melange(couleur, "#ffffff", 0.5),
      fond: melange(noir, couleur, 0.03),
      ent1: melange(noir, couleur, 0.15),
      ent2: melange(noir, couleur, 0.09),
      bord: melange(noir, couleur, 0.28),
      bot: melange(noir, couleur, 0.17),
      muet: melange("#b8b8b8", couleur, 0.25),
      ph: melange("#8c8c8c", couleur, 0.2),
      texte: melange("#f5f5f5", couleur, 0.06),
      sur: claire ? "#111111" : "#ffffff"
    };
  }

  // Polices du site NexBot
  if (!document.getElementById("nexbot-polices")) {
    var lien = document.createElement("link");
    lien.id = "nexbot-polices";
    lien.rel = "stylesheet";
    lien.href = "https://fonts.googleapis.com/css2?family=Michroma&family=Instrument+Sans:wght@400;500;600&display=swap";
    document.head.appendChild(lien);
  }

  // Langue de l'interface : celle de la page du site, sinon celle du navigateur
  var langueBrute = (document.documentElement.lang || navigator.language || "fr").toLowerCase();
  var LANG = langueBrute.indexOf("en") === 0 ? "en" : "fr";
  var T = {
    fr: { ouvrir: "Ouvrir l'assistant ", assistant: "Assistant ", fermer: "Fermer", enLigne: "En ligne",
          placeholder: "Écrivez votre message…", champ: "Votre message", envoyer: "Envoyer",
          pied: "Propulsé par NexBot", accueil: "Bonjour! Comment puis-je vous aider?",
          erreur: "Désolé, une erreur est survenue. Réessayez dans un instant.",
          connexion: "Désolé, je n'arrive pas à me connecter. Réessayez dans un instant." },
    en: { ouvrir: "Open the assistant ", assistant: "Assistant ", fermer: "Close", enLigne: "Online",
          placeholder: "Type your message…", champ: "Your message", envoyer: "Send",
          pied: "Powered by NexBot", accueil: "Hello! How can I help you?",
          erreur: "Sorry, something went wrong. Please try again in a moment.",
          connexion: "Sorry, I can't connect right now. Please try again in a moment." }
  }[LANG];

  var sessionId = lire(cleSession) || "";
  var enCours = false;

  fetch(base + "/api/" + encodeURIComponent(idClient) + "/config?lang=" + LANG)
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(demarrer)
    .catch(function (e) { console.error("widget.js : impossible de charger la config", e); });

  function el(tag, attrs, enfants) {
    var n = document.createElement(tag);
    for (var k in (attrs || {})) {
      if (k === "style") n.style.cssText = attrs[k];
      else if (k === "text") n.textContent = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    (enfants || []).forEach(function (c) { n.appendChild(c); });
    return n;
  }

  function demarrer(cfg) {
    var choix = script.getAttribute("data-couleur") || cfg.couleur;
    if (String(choix).toLowerCase() === "auto") choix = detecterCouleurSite();
    var P = palette(choix);
    var hote = el("div", { style: "position:fixed;right:20px;bottom:20px;z-index:2147483000;font-family:'Instrument Sans',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;" });
    var ombre = hote.attachShadow ? hote.attachShadow({ mode: "open" }) : hote;

    var css = el("style", { text:
      "*{box-sizing:border-box}" +
      ".bulle{width:64px;height:64px;border-radius:50%;border:1.5px solid " + P.c + ";cursor:pointer;background:#000;padding:0;overflow:hidden;box-shadow:0 0 28px " + rgba(P.c, .55) + ",0 6px 24px rgba(0,0,0,.5);transition:transform .2s,box-shadow .2s}" +
      ".bulle:hover{transform:scale(1.06);box-shadow:0 0 36px " + rgba(P.c, .75) + ",0 6px 24px rgba(0,0,0,.5)}" +
      ".bulle img{width:100%;height:100%;object-fit:cover;display:block;transform:scale(1.9);transform-origin:51% 50%}" +
      ".bulle:focus-visible,.envoyer:focus-visible,.fermer:focus-visible{outline:2px solid " + P.clair + ";outline-offset:3px}" +
      ".panneau{display:none;position:absolute;right:0;bottom:80px;width:370px;max-width:calc(100vw - 40px);height:540px;max-height:calc(100vh - 120px);background:" + P.fond + ";border:1px solid " + P.bord + ";border-radius:22px;box-shadow:0 0 60px " + rgba(P.c, .3) + ",0 16px 48px rgba(0,0,0,.6);overflow:hidden;flex-direction:column;color:" + P.texte + "}" +
      ".panneau.ouvert{display:flex}" +
      ".entete{background:linear-gradient(135deg," + P.ent1 + "," + P.ent2 + ");border-bottom:1px solid " + P.bord + ";padding:14px 16px;display:flex;align-items:center;gap:12px}" +
      ".avatar{width:38px;height:38px;border-radius:50%;overflow:hidden;background:#000;border:1px solid " + P.c + ";flex:none}" +
      ".avatar img{width:100%;height:100%;object-fit:cover;display:block;transform:scale(1.9);transform-origin:51% 50%}" +
      ".titre{font-family:'Michroma','Instrument Sans',system-ui,sans-serif;font-size:12px;letter-spacing:.08em;line-height:1.3;text-transform:uppercase}" +
      ".sous{font-size:11.5px;color:" + P.muet + ";display:flex;align-items:center;gap:6px;margin-top:2px}" +
      ".sous::before{content:'';width:7px;height:7px;border-radius:50%;background:#5fd3a0;display:block}" +
      ".fermer{margin-left:auto;background:none;border:0;color:" + P.muet + ";font-size:24px;cursor:pointer;line-height:1}" +
      ".fermer:hover{color:#fff}" +
      ".messages{flex:1;overflow-y:auto;padding:16px;background:" + P.fond + ";display:flex;flex-direction:column;gap:10px}" +
      ".messages::-webkit-scrollbar{width:6px}.messages::-webkit-scrollbar-thumb{background:" + P.bord + ";border-radius:3px}" +
      ".m{max-width:84%;padding:11px 15px;border-radius:18px;font-size:14.5px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}" +
      ".bot{background:" + P.bot + ";color:" + P.texte + ";align-self:flex-start;border-bottom-left-radius:4px}" +
      ".moi{background:linear-gradient(135deg," + P.haut + "," + P.bas + ");color:" + P.sur + ";align-self:flex-end;border-bottom-right-radius:4px}" +
      ".ecrit{opacity:.6;font-style:italic}" +
      ".zone{display:flex;gap:8px;padding:12px;border-top:1px solid " + P.bord + ";background:" + P.ent2 + "}" +
      ".zone input{flex:1;min-width:0;background:" + P.fond + ";color:" + P.texte + ";border:1px solid " + P.bord + ";border-radius:999px;padding:11px 16px;font-size:16px;font-family:inherit;outline:none}" +
      ".zone input::placeholder{color:" + P.ph + "}" +
      ".zone input:focus{border-color:" + P.c + "}" +
      ".envoyer{background:linear-gradient(135deg," + P.haut2 + "," + P.bas + ");color:" + P.sur + ";border:0;border-radius:999px;padding:0 18px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;box-shadow:0 4px 16px " + rgba(P.c, .35) + "}" +
      ".envoyer:hover{filter:brightness(1.1)}" +
      ".envoyer:disabled{opacity:.5;cursor:default}" +
      ".pied{font-size:10.5px;color:" + P.ph + ";text-align:center;padding:0 12px 10px;background:" + P.ent2 + ";letter-spacing:.04em}" +
      "@media (max-width:480px){.panneau{position:fixed;right:10px;left:10px;bottom:90px;width:auto;max-width:none}}"
    });

    function creerLogo() {
      return el("img", { src: LOGO, alt: "NexBot", draggable: "false" });
    }

    // --- Bulle ---
    var bulle = el("button", { "class": "bulle", type: "button", "aria-label": T.ouvrir + cfg.nom }, [creerLogo()]);

    // --- Panneau ---
    var fermer = el("button", { "class": "fermer", type: "button", "aria-label": T.fermer, text: "×" });
    var entete = el("div", { "class": "entete" }, [
      el("div", { "class": "avatar" }, [creerLogo()]),
      el("div", {}, [
        el("div", { "class": "titre", text: cfg.nom }),
        el("div", { "class": "sous", text: T.enLigne })
      ]),
      fermer
    ]);

    var zoneMessages = el("div", { "class": "messages", role: "log", "aria-live": "polite" });

    var champ = el("input", { type: "text", placeholder: T.placeholder, maxlength: "1000", "aria-label": T.champ, autocomplete: "off" });
    var envoyer = el("button", { "class": "envoyer", type: "submit", text: T.envoyer });
    var formulaire = el("form", { "class": "zone" }, [champ, envoyer]);

    var pied = el("div", { "class": "pied", text: T.pied });
    var panneau = el("div", { "class": "panneau", role: "dialog", "aria-label": T.assistant + cfg.nom }, [entete, zoneMessages, formulaire, pied]);

    ombre.appendChild(css);
    ombre.appendChild(panneau);
    ombre.appendChild(bulle);
    document.body.appendChild(hote);

    // --- Comportement ---
    function ajouter(texte, classe) {
      var m = el("div", { "class": "m " + classe, text: texte });
      zoneMessages.appendChild(m);
      zoneMessages.scrollTop = zoneMessages.scrollHeight;
      return m;
    }

    var accueilAffiche = false;
    function ouvrir() {
      panneau.classList.add("ouvert");
      if (!accueilAffiche) {
        accueilAffiche = true;
        ajouter(cfg.accueil || T.accueil, "bot");
      }
      setTimeout(function () { champ.focus(); }, 50);
    }
    function fermerPanneau() {
      panneau.classList.remove("ouvert");
      bulle.focus();
    }

    bulle.addEventListener("click", function () {
      if (panneau.classList.contains("ouvert")) fermerPanneau(); else ouvrir();
    });
    fermer.addEventListener("click", fermerPanneau);
    panneau.addEventListener("keydown", function (e) {
      if (e.key === "Escape") fermerPanneau();
    });

    formulaire.addEventListener("submit", function (e) {
      e.preventDefault();
      var texte = champ.value.trim();
      if (!texte || enCours) return;

      champ.value = "";
      ajouter(texte, "moi");
      enCours = true;
      envoyer.disabled = true;
      var attente = ajouter("…", "bot ecrit");

      fetch(base + "/api/" + encodeURIComponent(idClient) + "/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: texte, lang: LANG })
      })
        .then(function (r) {
          return r.json().catch(function () { return {}; }).then(function (data) {
            return { ok: r.ok, data: data };
          });
        })
        .then(function (res) {
          var d = res.data || {};
          if (d.session_id) { sessionId = d.session_id; ecrire(cleSession, sessionId); }
          attente.className = "m bot";
          attente.textContent = d.reponse || T.erreur;
        })
        .catch(function () {
          attente.className = "m bot";
          attente.textContent = T.connexion;
        })
        .then(function () {
          enCours = false;
          envoyer.disabled = false;
          zoneMessages.scrollTop = zoneMessages.scrollHeight;
          champ.focus();
        });
    });
  }
})();
