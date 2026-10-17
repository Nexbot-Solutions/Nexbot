/*
 * Widget NexBot — à coller sur le site du client :
 *
 *   <script src="https://TON-SERVEUR/widget.js" data-client="ID_DU_CLIENT" async></script>
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
 
  // Polices du site NexBot
  if (!document.getElementById("nexbot-polices")) {
    var lien = document.createElement("link");
    lien.id = "nexbot-polices";
    lien.rel = "stylesheet";
    lien.href = "https://fonts.googleapis.com/css2?family=Michroma&family=Instrument+Sans:wght@400;500;600&display=swap";
    document.head.appendChild(lien);
  }
 
  var sessionId = lire(cleSession) || "";
  var enCours = false;
 
  fetch(base + "/api/" + encodeURIComponent(idClient) + "/config")
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
    var hote = el("div", { style: "position:fixed;right:20px;bottom:20px;z-index:2147483000;font-family:'Instrument Sans',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;" });
    var ombre = hote.attachShadow ? hote.attachShadow({ mode: "open" }) : hote;
 
    var css = el("style", { text:
      "*{box-sizing:border-box}" +
      ".bulle{width:64px;height:64px;border-radius:50%;border:1.5px solid #8b5cf6;cursor:pointer;background:#000;padding:0;overflow:hidden;box-shadow:0 0 28px rgba(139,92,246,.55),0 6px 24px rgba(0,0,0,.5);transition:transform .2s,box-shadow .2s}" +
      ".bulle:hover{transform:scale(1.06);box-shadow:0 0 36px rgba(139,92,246,.75),0 6px 24px rgba(0,0,0,.5)}" +
      ".bulle img{width:100%;height:100%;object-fit:cover;display:block;transform:scale(1.9);transform-origin:51% 50%}" +
      ".bulle:focus-visible,.envoyer:focus-visible,.fermer:focus-visible{outline:2px solid #bda4ff;outline-offset:3px}" +
      ".panneau{display:none;position:absolute;right:0;bottom:80px;width:370px;max-width:calc(100vw - 40px);height:540px;max-height:calc(100vh - 120px);background:#07050d;border:1px solid #2a1f47;border-radius:22px;box-shadow:0 0 60px rgba(139,92,246,.3),0 16px 48px rgba(0,0,0,.6);overflow:hidden;flex-direction:column;color:#f3f0fa}" +
      ".panneau.ouvert{display:flex}" +
      ".entete{background:linear-gradient(135deg,#1a1033,#120c22);border-bottom:1px solid #2a1f47;padding:14px 16px;display:flex;align-items:center;gap:12px}" +
      ".avatar{width:38px;height:38px;border-radius:50%;overflow:hidden;background:#000;border:1px solid #8b5cf6;flex:none}" +
      ".avatar img{width:100%;height:100%;object-fit:cover;display:block;transform:scale(1.9);transform-origin:51% 50%}" +
      ".titre{font-family:'Michroma','Instrument Sans',system-ui,sans-serif;font-size:12px;letter-spacing:.08em;line-height:1.3;text-transform:uppercase}" +
      ".sous{font-size:11.5px;color:#a99fc4;display:flex;align-items:center;gap:6px;margin-top:2px}" +
      ".sous::before{content:'';width:7px;height:7px;border-radius:50%;background:#5fd3a0;display:block}" +
      ".fermer{margin-left:auto;background:none;border:0;color:#a99fc4;font-size:24px;cursor:pointer;line-height:1}" +
      ".fermer:hover{color:#fff}" +
      ".messages{flex:1;overflow-y:auto;padding:16px;background:#07050d;display:flex;flex-direction:column;gap:10px}" +
      ".messages::-webkit-scrollbar{width:6px}.messages::-webkit-scrollbar-thumb{background:#2a1f47;border-radius:3px}" +
      ".m{max-width:84%;padding:11px 15px;border-radius:18px;font-size:14.5px;line-height:1.45;white-space:pre-wrap;word-wrap:break-word}" +
      ".bot{background:#1d1433;color:#f3f0fa;align-self:flex-start;border-bottom-left-radius:4px}" +
      ".moi{background:linear-gradient(135deg,#9a6dff,#5b2fd6);color:#fff;align-self:flex-end;border-bottom-right-radius:4px}" +
      ".ecrit{opacity:.6;font-style:italic}" +
      ".zone{display:flex;gap:8px;padding:12px;border-top:1px solid #2a1f47;background:#120c22}" +
      ".zone input{flex:1;min-width:0;background:#07050d;color:#f3f0fa;border:1px solid #2a1f47;border-radius:999px;padding:11px 16px;font-size:14.5px;font-family:inherit;outline:none}" +
      ".zone input::placeholder{color:#7d7399}" +
      ".zone input:focus{border-color:#8b5cf6}" +
      ".envoyer{background:linear-gradient(135deg,#a47bff,#5b2fd6);color:#fff;border:0;border-radius:999px;padding:0 18px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;box-shadow:0 4px 16px rgba(139,92,246,.35)}" +
      ".envoyer:hover{filter:brightness(1.1)}" +
      ".envoyer:disabled{opacity:.5;cursor:default}" +
      ".pied{font-size:10.5px;color:#7d7399;text-align:center;padding:0 12px 10px;background:#120c22;letter-spacing:.04em}" +
      "@media (max-width:480px){.panneau{position:fixed;right:10px;left:10px;bottom:90px;width:auto;max-width:none}}"
    });
 
    function creerLogo() {
      return el("img", { src: LOGO, alt: "NexBot", draggable: "false" });
    }
 
    // --- Bulle ---
    var bulle = el("button", { "class": "bulle", type: "button", "aria-label": "Ouvrir l'assistant " + cfg.nom }, [creerLogo()]);
 
    // --- Panneau ---
    var fermer = el("button", { "class": "fermer", type: "button", "aria-label": "Fermer", text: "×" });
    var entete = el("div", { "class": "entete" }, [
      el("div", { "class": "avatar" }, [creerLogo()]),
      el("div", {}, [
        el("div", { "class": "titre", text: cfg.nom }),
        el("div", { "class": "sous", text: "En ligne" })
      ]),
      fermer
    ]);
 
    var zoneMessages = el("div", { "class": "messages", role: "log", "aria-live": "polite" });
 
    var champ = el("input", { type: "text", placeholder: "Écrivez votre message…", maxlength: "1000", "aria-label": "Votre message", autocomplete: "off" });
    var envoyer = el("button", { "class": "envoyer", type: "submit", text: "Envoyer" });
    var formulaire = el("form", { "class": "zone" }, [champ, envoyer]);
 
    var pied = el("div", { "class": "pied", text: "Propulsé par NexBot" });
    var panneau = el("div", { "class": "panneau", role: "dialog", "aria-label": "Assistant " + cfg.nom }, [entete, zoneMessages, formulaire, pied]);
 
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
        ajouter(cfg.accueil || "Bonjour! Comment puis-je vous aider?", "bot");
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
        body: JSON.stringify({ session_id: sessionId, message: texte })
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
          attente.textContent = d.reponse || "Désolé, une erreur est survenue. Réessayez dans un instant.";
        })
        .catch(function () {
          attente.className = "m bot";
          attente.textContent = "Désolé, je n'arrive pas à me connecter. Réessayez dans un instant.";
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
