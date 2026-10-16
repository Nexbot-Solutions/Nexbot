"""Serveur web : expose les bots aux sites des clients.

Démarrer (test) :   python serveur.py
Démarrer (prod) :   gunicorn serveur:app --threads 8 --bind 0.0.0.0:$PORT

Routes :
  GET  /api/<id_client>/config    -> infos d'accueil du widget
  POST /api/<id_client>/message   -> {"session_id": "...", "message": "..."}
  GET  /widget.js                 -> le widget à coller sur le site du client
  GET  /demo                      -> page de démonstration
  GET  /sante                     -> vérification que le serveur roule
"""
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory

from bot import Bot, charger_client

BASE = Path(__file__).resolve().parent
LONGUEUR_MAX_MESSAGE = 1000
DUREE_SESSION_SEC = 30 * 60
MAX_SESSIONS = 2000
MAX_MESSAGES_PAR_MIN_PAR_IP = 20
TRUST_PROXY = os.environ.get("TRUST_PROXY", "false").lower() == "true"

app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")

CLIENTS = {}
SESSIONS = {}  # (id_client, session_id) -> {"bot": Bot, "vu": timestamp}
RECENTS_PAR_IP = defaultdict(deque)
VERROU = threading.Lock()


def charger_clients() -> None:
    """Lit tous les fichiers clients/*.json (ceux qui commencent par _ sont ignorés)."""
    CLIENTS.clear()
    for fichier in sorted((BASE / "clients").glob("*.json")):
        if fichier.stem.startswith("_"):
            continue
        config = charger_client(str(fichier))
        id_client = config.get("id") or fichier.stem
        config["id"] = id_client
        CLIENTS[id_client] = config


charger_clients()


# ---------- Sécurité : domaines autorisés (CORS) ----------
def origine_autorisee(config: dict, origine: str) -> bool:
    domaines = config.get("domaines_autorises") or []
    if not domaines:  # aucun domaine précisé = ouvert (OK pour les tests seulement)
        return True
    hote = (urlparse(origine).hostname or "").lower()
    for d in domaines:
        d = d.lower().lstrip(".")
        if hote == d or hote.endswith("." + d):
            return True
    return False


@app.after_request
def entetes_securite(reponse):
    reponse.headers.setdefault("X-Content-Type-Options", "nosniff")
    reponse.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    reponse.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return reponse


@app.after_request
def entetes_cors(reponse):
    origine = request.headers.get("Origin")
    if origine and request.path.startswith("/api/"):
        id_client = request.view_args.get("id_client") if request.view_args else None
        config = CLIENTS.get(id_client)
        if config and origine_autorisee(config, origine):
            reponse.headers["Access-Control-Allow-Origin"] = origine
            reponse.headers["Vary"] = "Origin"
            reponse.headers["Access-Control-Allow-Headers"] = "Content-Type"
            reponse.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return reponse


def trop_de_requetes(ip: str) -> bool:
    maintenant = time.time()
    with VERROU:
        file = RECENTS_PAR_IP[ip]
        while file and maintenant - file[0] > 60:
            file.popleft()
        if len(file) >= MAX_MESSAGES_PAR_MIN_PAR_IP:
            return True
        file.append(maintenant)
    return False


def nettoyer_sessions() -> None:
    maintenant = time.time()
    with VERROU:
        for cle in [k for k, v in SESSIONS.items() if maintenant - v["vu"] > DUREE_SESSION_SEC]:
            del SESSIONS[cle]
        if len(SESSIONS) > MAX_SESSIONS:
            for cle in sorted(SESSIONS, key=lambda k: SESSIONS[k]["vu"])[: len(SESSIONS) - MAX_SESSIONS]:
                del SESSIONS[cle]


# ---------- Routes ----------
@app.route("/sante")
def sante():
    return jsonify(ok=True, clients=len(CLIENTS))


@app.route("/api/<id_client>/config", methods=["GET", "OPTIONS"])
def config_client(id_client):
    config = CLIENTS.get(id_client)
    if not config:
        return jsonify(erreur="Client inconnu"), 404
    origine = request.headers.get("Origin")
    if origine and not origine_autorisee(config, origine):
        return jsonify(erreur="Domaine non autorisé"), 403
    return jsonify(
        nom=config["nom_entreprise"],
        accueil=config.get("message_accueil", "Bonjour! Comment puis-je vous aider?"),
        couleur=config.get("couleur", "#2F5BEA"),
    )


@app.route("/api/<id_client>/message", methods=["POST", "OPTIONS"])
def message(id_client):
    if request.method == "OPTIONS":
        return ("", 204)

    config = CLIENTS.get(id_client)
    if not config:
        return jsonify(erreur="Client inconnu"), 404

    origine = request.headers.get("Origin")
    if origine and not origine_autorisee(config, origine):
        return jsonify(erreur="Domaine non autorisé"), 403

    if TRUST_PROXY:
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    else:
        ip = request.remote_addr or "?"
    if trop_de_requetes(ip):
        return jsonify(reponse="Un instant, vous écrivez trop vite. Réessayez dans quelques secondes."), 429

    donnees = request.get_json(silent=True) or {}
    texte = str(donnees.get("message", "")).strip()
    if not texte:
        return jsonify(erreur="Message vide"), 400
    texte = texte[:LONGUEUR_MAX_MESSAGE]

    session_id = str(donnees.get("session_id") or "")[:64] or uuid.uuid4().hex
    nettoyer_sessions()
    cle = (id_client, session_id)
    with VERROU:
        session = SESSIONS.get(cle)
        if session is None:
            session = {"bot": Bot(config), "vu": time.time()}
            SESSIONS[cle] = session
        session["vu"] = time.time()

    reponse = session["bot"].repondre(texte)
    return jsonify(reponse=reponse, session_id=session_id)


@app.route("/widget.js")
def widget():
    reponse = send_from_directory(app.static_folder, "widget.js", mimetype="application/javascript")
    reponse.headers["Cache-Control"] = "public, max-age=300"
    reponse.headers["Access-Control-Allow-Origin"] = "*"
    return reponse


@app.route("/logo.svg")
def logo():
    reponse = send_from_directory(app.static_folder, "logo.svg", mimetype="image/svg+xml")
    reponse.headers["Access-Control-Allow-Origin"] = "*"
    return reponse


@app.route("/demo")
def demo():
    return send_from_directory(app.static_folder, "demo.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"{len(CLIENTS)} client(s) chargé(s) : {', '.join(CLIENTS) or 'aucun'}")
    print(f"Démo : http://localhost:{port}/demo")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
