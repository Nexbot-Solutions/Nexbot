/*
 * Widget de clavardage — à coller sur le site du client :
 *
 *   <script src="https://TON-SERVEUR/widget.js" data-client="ID_DU_CLIENT" async></script>
 */
(function () {
  var script = document.currentScript || document.querySelector('script[src*="widget.js"]');
  if (!script) return;
  var idClient = script.getAttribute("data-client");
  if (!idClient) return console.error("widget.js : attribut data-client manquant");
  var base = new URL(script.src).origin;
  var cleSession = "bot_session_" + idClient;

  function lire(cle) { try { return localStorage.getItem(cle); } catch (e) { return null; } }
  function ecrire(cle, val) { try { localStorage.setItem(cle, val); } catch (e) {} }

  var sessionId = lire(cleSession) || "";
  var enCours = false;

  fetch(base + "/api/" + encodeURIComponent(idClient) + "/config")
    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
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
    var couleur = cfg.couleur || "#2F5BEA";
    var hote = el("div", { style: "position:fixed;right:20px;bottom:20px;z-index:2147483000;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;" });
    var ombre = hote.attachShadow ? hote.attachShadow({ mode: "open" }) : hote;

    var css = el("style", { text:
      "*{box-sizing:border-box}" +
      ".bulle{width:62px;height:62px;border-radius:50%;border:0;cursor:pointer;background:#fff;box-shadow:0 6px 24px rgba(0,0,0,.25);padding:0;display:flex;align-items:center;justify-content:center}" +
      ".bulle img{width:46px;height:46px}" +
      ".bulle:focus-visible,.envoyer:focus-visible,.fermer:focus-visible{outline:3px solid " + couleur + ";outline-offset:2px}" +
      ".panneau{display:none;position:absolute;right:0;bottom:78px;width:360px;max-width:calc(100vw - 40px);height:520px;max-height:calc(100vh - 120px);background:#fff;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.28);overflow:hidden;flex-direction:column}" +
      ".panneau.ouvert{display:flex}" +
      ".entete{background:" + couleur + ";color:#fff;padding:14px 16px;display:flex;align-items:center;gap:10px}" +
      ".entete img{width:30px;height:30px;background:#fff;border-radius:50%;padding:2px}" +
      ".titre{font-weight:600;font-size:15px;line-height:1.2}" +
      ".sous{font-size:11px;opacity:.9}" +
      ".fermer{margin-left:auto;background:none;border:0;color:#fff;font-size:22px;cursor:pointer;line-height:1}" +
      ".messages{flex:1;overflow-y:auto;padding:14px;background:#f5f7fb;display:flex;flex-direction:column;gap:8px}" +
      ".m{max-width:82%;padding:9px 12px;border-radius:14px;font-size:14px;line-height:1.4;white-space:pre-wrap;word-wrap:break-word}" +
      ".bot{background:#fff;color:#1c2330;align-self:flex-start;border-bottom-left-radius:4px;box-shadow:0 1px 2px rgba(0,0,0,.08)}" +
      ".moi{background:" + couleur + ";color:#fff;align-self:flex-end;border-bottom-right-radius:4px}" +
      ".ecrit{opacity:.6;font-style:italic}" +
      ".zone{display:flex;gap:8px;padding:10px;border-top:1px solid #e3e7ef;background:#fff}" +
      ".zone input{flex:1;border:1px solid #cfd6e4;border-radius:20px;padding:10px 14px;font-size:14px;outline:none}" +
      ".zone input:focus{border-color:" + couleur + "}" +
      ".envoyer{background:" + couleur + ";color:#fff;border:0;border-radius:20px;padding:0 16px;font-size:14px;cursor:pointer}" +
      ".envoyer:disabled{opacity:.5;cursor:default}" +
      ".pied{font-size:10.5px;color:#6b7385;text-align:center;padding:0 10px 8px;background:#fff}"
    });

    var bulle = el("button", { "class": "bulle", "aria-label": "Ouvrir le clavardage" }, [
      el("img", { src: base + "/logo.svg", alt: "" })
    ]);
    var fermer = el("button", { "class": "fermer", "aria-label": "Fermer", text: "×" });
    var entete = el("div", { "class": "entete" }, [
      el("img", { src: base + "/logo.svg", alt: "" }),
      el("div", {}, [
        el("div", { "class": "titre", text: cfg.nom }),
        el("div", { "class": "sous", text: "Assistant virtuel" })
      ]),
      fermer
    ]);
    var zoneMessages = el("div", { "class": "messages", "aria-live": "polite" });
    var champ = el("input", { type: "text", placeholder: "Écrivez votre message…", maxlength: "1000", "aria-label": "Votre message" });
    var envoyer = el("button", { "class": "envoyer", text: "Envoyer" });
    var zone = el("form", { "class": "zone" }, [champ, envoyer]);
    var pied = el("div", { "class": "pied", text: "Vous parlez à un assistant virtuel. Évitez de partager des renseignements personnels sensibles." });
    var panneau = el("div", { "class": "panneau", role: "dialog", "aria-label": "Clavardage" }, [entete, zoneMessages, zone, pied]);

    ombre.appendChild(css);
    ombre.appendChild(panneau);
    ombre.appendChild(bulle);
    document.body.appendChild(hote);

    function ajouter(texte, classe) {
      var m = el("div", { "class": "m " + classe, text: texte });
      zoneMessages.appendChild(m);
      zoneMessages.scrollTop = zoneMessages.scrollHeight;
      return m;
    }

    var accueilAffiche = false;
    function basculer(ouvrir) {
      var veut = typeof ouvrir === "boolean" ? ouvrir : !panneau.classList.contains("ouvert");
      panneau.classList.toggle("ouvert", veut);
      if (veut) {
        if (!accueilAffiche) { ajouter(cfg.accueil, "bot"); accueilAffiche = true; }
        champ.focus();
      }
    }
    bulle.addEventListener("click", function () { basculer(); });
    fermer.addEventListener("click", function () { basculer(false); });

    zone.addEventListener("submit", function (e) {
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
        body: JSON.stringify({ session_id: sessionId, message: texte })
      })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .then(function (d) {
          if (d.session_id) { sessionId = d.session_id; ecrire(cleSession, sessionId); }
          attente.className = "m bot";
          attente.textContent = d.reponse || "Désolé, une erreur est survenue. Veuillez réessayer.";
        })
        .catch(function () {
          attente.className = "m bot";
          attente.textContent = "Connexion impossible pour le moment. Veuillez réessayer.";
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
