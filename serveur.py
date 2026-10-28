"""Serveur web : expose les bots aux sites des clients.

Démarrer (test) :   python serveur.py
Démarrer (prod) :   gunicorn serveur:app --threads 8 --bind 0.0.0.0:$PORT

Routes :
  GET  /api/<id_client>/config    -> infos d'accueil du widget
  POST /api/<id_client>/message   -> {"session_id": "...", "message": "..."}
  GET  /widget.js                 -> le widget à coller sur le site du client
  GET  /demo                      -> page de démonstration
  GET  /confidentialite           -> politique de confidentialité
  GET  /conditions                -> conditions d'utilisation
  GET  /en, /en/privacy, /en/terms -> version anglaise du site
  GET  /bienvenue, /en/welcome    -> formulaire à remplir après l'achat d'une offre
  POST /api/onboarding            -> reçoit le formulaire et l'envoie par courriel à l'équipe NexBot
  GET  /sante                     -> vérification que le serveur roule
"""
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request, send_from_directory

from bot import Bot, charger_client, courriel_configure, envoyer_courriel

BASE = Path(__file__).resolve().parent
LONGUEUR_MAX_MESSAGE = 1000
DUREE_SESSION_SEC = 30 * 60
MAX_SESSIONS = 2000
MAX_MESSAGES_PAR_MIN_PAR_IP = 20
TRUST_PROXY = os.environ.get("TRUST_PROXY", "false").lower() == "true"

app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 200_000  # aucune requête légitime n'approche cette taille

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
    en = request.args.get("lang", "fr").lower().startswith("en")
    if en:
        accueil = config.get("message_accueil_en") or "Hello! How can I help you?"
    else:
        accueil = config.get("message_accueil", "Bonjour! Comment puis-je vous aider?")
    return jsonify(
        nom=config["nom_entreprise"],
        accueil=accueil,
        couleur=config.get("couleur", "auto"),
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
            langue = "en" if str(donnees.get("lang", "fr")).lower().startswith("en") else "fr"
            session = {"bot": Bot(config, langue), "vu": time.time()}
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


@app.route("/")
def accueil():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/demo")
def demo():
    return send_from_directory(app.static_folder, "demo.html")


@app.route("/confidentialite")
def confidentialite():
    return send_from_directory(app.static_folder, "confidentialite.html")


@app.route("/conditions")
def conditions():
    return send_from_directory(app.static_folder, "conditions.html")


@app.route("/en")
def accueil_en():
    return send_from_directory(app.static_folder, "en.html")


@app.route("/en/privacy")
def privacy_en():
    return send_from_directory(app.static_folder, "privacy-en.html")


@app.route("/en/terms")
def terms_en():
    return send_from_directory(app.static_folder, "terms-en.html")


# ---------- Formulaire à remplir après l'achat ----------
DEST_ONBOARDING = os.environ.get("ONBOARDING_DEST", "nexbot.contact@gmail.com")
MAX_ONBOARDING_PAR_HEURE_PAR_IP = 5
RECENTS_ONBOARDING = defaultdict(deque)
RE_COURRIEL = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]{2,}$")
PLANS_VALIDES = {"essentiel": "Essentiel", "pro": "Pro", "business": "Business"}
# (clé du formulaire, libellé dans le courriel, longueur maximale)
CHAMPS_ONBOARDING = [
    ("entreprise", "Nom de l'entreprise", 150),
    ("contact_nom", "Nom du contact", 150),
    ("courriel", "Courriel", 200),
    ("telephone", "Téléphone", 40),
    ("site_web", "Site web où installer l'assistant", 300),
    ("couleur", "Couleur du widget", 40),
    ("langues", "Langues de l'assistant", 60),
    ("heures", "Heures d'ouverture", 1500),
    ("coordonnees", "Coordonnées à afficher si l'assistant ne sait pas", 1500),
    ("services_prix", "Services, produits et prix", 6000),
    ("faq", "Questions fréquentes et réponses", 8000),
    ("politiques", "Politiques (retours, livraison, annulation...)", 4000),
    ("courriel_demandes", "Courriel qui reçoit les demandes transmises", 200),
    ("ton", "Ton souhaité", 300),
    ("sujets_interdits", "Sujets que l'assistant doit refuser", 2000),
    ("personnalite", "Personnalité de marque", 3000),
]


def ip_du_client() -> str:
    if TRUST_PROXY:
        return request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
    return request.remote_addr or "?"


def trop_de_formulaires(ip: str) -> bool:
    maintenant = time.time()
    with VERROU:
        file = RECENTS_ONBOARDING[ip]
        while file and maintenant - file[0] > 3600:
            file.popleft()
        if len(file) >= MAX_ONBOARDING_PAR_HEURE_PAR_IP:
            return True
        file.append(maintenant)
    return False


@app.route("/api/onboarding", methods=["POST"])
def onboarding():
    donnees = request.get_json(silent=True)
    if not isinstance(donnees, dict):
        return jsonify(erreur="Requête invalide."), 400
    if str(donnees.get("website", "")).strip():  # champ caché que seuls les robots remplissent
        return jsonify(ok=True)

    en = str(donnees.get("lang", "fr")).lower().startswith("en")

    def msg(fr: str, ang: str) -> str:
        return ang if en else fr

    if trop_de_formulaires(ip_du_client()):
        return jsonify(erreur=msg("Trop d'envois depuis cette adresse. Réessayez plus tard ou écrivez-nous par courriel.",
                                  "Too many submissions from this address. Try again later or email us.")), 429

    valeurs = {}
    for cle, _libelle, maximum in CHAMPS_ONBOARDING:
        brut = donnees.get(cle, "")
        valeurs[cle] = brut.replace("\r", "").strip()[:maximum] if isinstance(brut, str) else ""
    plan = PLANS_VALIDES.get(str(donnees.get("plan", "")).lower())

    if not plan:
        return jsonify(erreur=msg("Choisissez votre offre.", "Choose your plan.")), 400
    if not valeurs["entreprise"] or not valeurs["contact_nom"]:
        return jsonify(erreur=msg("Indiquez le nom de l'entreprise et votre nom.",
                                  "Enter the business name and your name.")), 400
    if not RE_COURRIEL.match(valeurs["courriel"]):
        return jsonify(erreur=msg("Entrez un courriel valide.", "Enter a valid email address.")), 400
    if valeurs["courriel_demandes"] and not RE_COURRIEL.match(valeurs["courriel_demandes"]):
        return jsonify(erreur=msg("Le courriel qui reçoit les demandes n'est pas valide.",
                                  "The email that receives requests is not valid.")), 400
    if donnees.get("consentement") is not True:
        return jsonify(erreur=msg("Cochez la case d'autorisation pour envoyer le formulaire.",
                                  "Tick the authorization box to submit the form.")), 400

    if not courriel_configure():
        return jsonify(erreur=msg("L'envoi n'est pas disponible pour le moment. Écrivez-nous à nexbot.contact@gmail.com.",
                                  "Submission is unavailable right now. Please email us at nexbot.contact@gmail.com.")), 503

    maintenant = datetime.now(ZoneInfo("America/Toronto")).strftime("%Y-%m-%d %H:%M")
    lignes = [
        f"Nouveau client : {valeurs['entreprise']}",
        f"Offre : {plan}",
        f"Formulaire rempli en : {'anglais' if en else 'français'}",
        f"Reçu le : {maintenant} (heure de l'Est)",
        "Autorisation d'utiliser ces renseignements : oui",
        "",
    ]
    for cle, libelle, _maximum in CHAMPS_ONBOARDING:
        lignes.append(f"{libelle} :")
        lignes.append(valeurs[cle] or "(non rempli)")
        lignes.append("")
    try:
        envoyer_courriel(
            DEST_ONBOARDING,
            f"[NexBot] Nouveau client : {valeurs['entreprise']} ({plan})",
            "\n".join(lignes),
            repondre_a=valeurs["courriel"],
        )
    except Exception as erreur:  # on ne journalise pas le contenu du formulaire
        print(f"Échec de l'envoi du formulaire client : {type(erreur).__name__}")
        return jsonify(erreur=msg("L'envoi a échoué. Réessayez, ou écrivez-nous à nexbot.contact@gmail.com.",
                                  "Sending failed. Try again, or email us at nexbot.contact@gmail.com.")), 502
    return jsonify(ok=True)


def page_privee(nom_fichier: str):
    """Page qui ne doit pas apparaître dans les moteurs de recherche."""
    reponse = send_from_directory(app.static_folder, nom_fichier)
    reponse.headers["X-Robots-Tag"] = "noindex, nofollow"
    reponse.headers["Cache-Control"] = "no-cache"
    return reponse


@app.route("/bienvenue")
def bienvenue():
    return page_privee("bienvenue.html")


@app.route("/en/welcome")
def welcome_en():
    return page_privee("welcome-en.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"{len(CLIENTS)} client(s) chargé(s) : {', '.join(CLIENTS) or 'aucun'}")
    print(f"Démo : http://localhost:{port}/demo")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
