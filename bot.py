"""Moteur unique pour les 3 plans : Essentiel, Pro, Business.

Un seul code. Ce qui change d'un client à l'autre, c'est son fichier
de configuration JSON dans le dossier clients/.
"""
import json
import os
import re
import smtplib
import ssl
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

PLANS = ("essentiel", "pro", "business")


def _charger_env() -> None:
    """Lit le fichier .env (s'il existe) pour les tests chez toi."""
    fichier = Path(__file__).resolve().parent / ".env"
    if not fichier.exists():
        return
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            os.environ.setdefault(cle.strip(), valeur.strip().strip('"').strip("'"))


_charger_env()

# Compteur de messages par jour, partagé entre toutes les conversations
# d'un même client (sinon chaque visiteur aurait sa propre limite).
_COMPTEURS = {}
_VERROU = threading.Lock()
_CLIENT_GEMINI = None
_FICHIER_COMPTEURS = Path(__file__).resolve().parent / "compteurs.json"

# Combien d'échanges le bot garde en mémoire selon le plan
MEMOIRE_ECHANGES = {"essentiel": 0, "pro": 6, "business": 20}

MODELE_GEMINI = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# ---------- Transmission d'une demande à l'équipe du client (courriel) ----------
MAX_TRANSMISSIONS_PAR_SESSION = 3
MAX_TRANSMISSIONS_PAR_JOUR = 30
_TRANSMISSIONS_JOUR = {}  # id_client -> [jour, nombre]
_REGEX_COURRIEL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")

# Phrases où le bot AFFIRME avoir transmis la demande (jamais acceptées sans envoi réussi)
_AFFIRME_TRANSMISSION = re.compile(
    r"(j'ai|je l'ai|je viens de|nous avons|on a)\s+(bien\s+)?(transmis|envoy[eé])"
    r"|je (la |le )?transmets"
    r"|(a|est|ont|sont)\s+(bien\s+)?(été\s+)?(transmis|envoy[eé])e?s?"
    r"|(i've|i have|i just|we've|we have)\s+(sent|forwarded|passed|submitted|relayed)"
    r"|(has|have) been (sent|forwarded|passed|submitted)",
    re.IGNORECASE,
)


def courriel_configure() -> bool:
    """Vrai si le serveur sait envoyer des courriels (clé Resend ou serveur SMTP)."""
    return bool(os.environ.get("RESEND_API_KEY") or os.environ.get("SMTP_HOST"))


def envoyer_courriel(destinataire: str, sujet: str, corps: str, repondre_a: str = "") -> None:
    """Envoie un courriel texte. Lève une exception si l'envoi échoue."""
    sujet = re.sub(r"[\r\n]+", " ", sujet)[:200]
    expediteur = os.environ.get("EXPEDITEUR") or os.environ.get("SMTP_USER") or "NexBot <onboarding@resend.dev>"
    cle = os.environ.get("RESEND_API_KEY")
    if cle:
        charge = {"from": expediteur, "to": [destinataire], "subject": sujet, "text": corps}
        if repondre_a:
            charge["reply_to"] = repondre_a
        requete = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(charge).encode("utf-8"),
            headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json", "User-Agent": "NexBot/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(requete, timeout=10):
                return
        except urllib.error.HTTPError as erreur:
            raise RuntimeError(f"Resend {erreur.code} : {erreur.read()[:200]!r}") from erreur
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = expediteur, destinataire, sujet
    if repondre_a:
        message["Reply-To"] = repondre_a
    message.set_content(corps)
    hote, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "465"))
    contexte = ssl.create_default_context()
    if port == 465:
        serveur = smtplib.SMTP_SSL(hote, port, timeout=10, context=contexte)
    else:
        serveur = smtplib.SMTP(hote, port, timeout=10)
        serveur.starttls(context=contexte)
    with serveur:
        if os.environ.get("SMTP_USER"):
            serveur.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
        serveur.send_message(message)


def normaliser(texte: str) -> str:
    """Minuscules, sans accents, pour comparer les mots-clés."""
    texte = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in texte if unicodedata.category(c) != "Mn")


MOTS_EN = {
    "the", "is", "are", "you", "your", "do", "does", "what", "how", "can", "could", "would",
    "hello", "hi", "hey", "thanks", "thank", "please", "price", "prices", "cost", "hours",
    "open", "when", "where", "which", "who", "why", "have", "has", "with", "for", "and",
    "my", "me", "i", "we", "need", "want", "help", "about", "this", "that", "of", "to", "in",
    "it", "a", "an", "much", "plan", "plans", "pricing", "support", "english",
}
MOTS_FR = {
    "le", "la", "les", "un", "une", "des", "du", "de", "est", "sont", "vous", "votre", "vos",
    "quoi", "comment", "quel", "quelle", "quels", "quand", "ou", "où", "pourquoi", "bonjour",
    "salut", "merci", "svp", "prix", "heures", "ouvert", "avez", "avoir", "je", "nous", "mon",
    "ma", "mes", "besoin", "veux", "voudrais", "aide", "pour", "avec", "et", "que", "qui",
    "ce", "cette", "ca", "c'est", "combien", "forfait", "forfaits", "offre", "offres", "francais",
}


def detecter_langue(texte: str, defaut: str = "fr") -> str:
    """Devine « fr » ou « en » d'après les mots du message. En cas d'égalité, garde la langue précédente."""
    mots = re.findall(r"[a-zà-ÿ']+", texte.lower())
    mots_sans_accent = [normaliser(m) for m in mots]
    en = sum(1 for m in mots_sans_accent if m in MOTS_EN)
    fr = sum(1 for m in mots_sans_accent if m in {normaliser(x) for x in MOTS_FR})
    if re.search(r"[àâçéèêëîïôûùüÿœ]", texte.lower()):
        fr += 2
    if en > fr:
        return "en"
    if fr > en:
        return "fr"
    return defaut if defaut in ("fr", "en") else "fr"


def charger_client(chemin: str) -> dict:
    config = json.loads(Path(chemin).read_text(encoding="utf-8"))
    if config.get("plan") not in PLANS:
        raise ValueError(f"Plan invalide : {config.get('plan')!r}. Choix : {PLANS}")
    return config


class Bot:
    def __init__(self, config: dict, langue: str = "fr"):
        self.config = config
        self.plan = config["plan"]
        self.langue = langue if langue in ("fr", "en") else "fr"
        self._transmissions = 0       # demandes transmises pendant cette conversation
        self._transmis_ce_tour = False
        self._message_courant = ""
        self.historique = []  # liste de {"role": "user"|"model", "text": "..."}

    # ---------- Point d'entrée ----------
    def _texte(self, cle: str, fr: str, en: str) -> str:
        """Message configuré du client dans la langue courante (cle_en pour l'anglais), sinon texte par défaut."""
        if self.langue == "en":
            return self.config.get(cle + "_en") or en
        return self.config.get(cle) or fr

    def repondre(self, message: str) -> str:
        self.langue = detecter_langue(message, self.langue)
        if self._limite_atteinte():
            return self._texte(
                "message_limite",
                "Nous avons beaucoup de demandes aujourd'hui. Veuillez nous joindre directement, merci!",
                "We are very busy today. Please contact us directly, thank you!",
            )

        self._message_courant = message
        self._transmis_ce_tour = False
        if self.plan == "essentiel":
            reponse = self._repondre_mots_cles(message)
        else:
            try:
                reponse = self._repondre_gemini(message)
            except Exception as erreur:  # panne réseau, clé invalide, quota...
                print(f"[avertissement] Gemini indisponible : {erreur}")
                reponse = self._repondre_mots_cles(message)
            reponse = self._corriger_fausse_transmission(reponse)

        self._memoriser(message, reponse)
        return reponse

    # ---------- Plan Essentiel : mots-clés ----------
    def _repondre_mots_cles(self, message: str) -> str:
        texte = normaliser(message)
        meilleur_score, meilleure_reponse = 0, None
        for entree in self.config.get("faq", []):
            mots = list(entree["mots_cles"]) + list(entree.get("mots_cles_en", []))
            score = sum(1 for mot in mots if normaliser(mot) in texte)
            if score > meilleur_score:
                reponse = entree["reponse"]
                if self.langue == "en" and entree.get("reponse_en"):
                    reponse = entree["reponse_en"]
                meilleur_score, meilleure_reponse = score, reponse
        if meilleure_reponse:
            return meilleure_reponse
        return self._texte(
            "message_inconnu",
            "Je n'ai pas la réponse à cette question. Un membre de l'équipe vous répondra bientôt.",
            "I don't have the answer to that question. A team member will get back to you soon.",
        )

    # ---------- Transmission à l'équipe ----------
    def _coordonnees(self) -> str:
        return self.config.get("coordonnees_humain") or "les coordonnées de l'entreprise indiquées plus haut"

    def transmission_possible(self) -> bool:
        """Le bot ne propose de transmettre que si tout est en place (sinon il mentirait)."""
        return (
            self.plan in ("pro", "business")
            and bool(_REGEX_COURRIEL.fullmatch(str(self.config.get("courriel_equipe", "")).strip()))
            and courriel_configure()
        )

    def _corriger_fausse_transmission(self, reponse: str) -> str:
        """Si la réponse dit « j'ai transmis » alors que rien n'a été envoyé, on le corrige."""
        if self._transmis_ce_tour or not _AFFIRME_TRANSMISSION.search(reponse):
            return reponse
        if self.langue == "en":
            note = ("Correction: your request has NOT been sent to the team. "
                    f"Please contact them directly: {self._coordonnees()}.")
        else:
            note = ("Précision : votre demande n'a PAS été transmise à l'équipe. "
                    f"Veuillez la joindre directement : {self._coordonnees()}.")
        print("[avertissement] Le bot a affirmé avoir transmis une demande sans envoi réussi.")
        return f"{reponse}\n\n{note}"

    def _transmettre(self, resume: str, priorite: str, nom: str, contact: str) -> str:
        """Envoie le courriel à l'équipe. Le texte retourné est lu par le modèle, qui doit le respecter."""
        resume, nom, contact = str(resume or "").strip()[:800], str(nom or "").strip()[:100], str(contact or "").strip()[:200]
        echec = f"Non transmis. Dis honnêtement au visiteur que la demande n'a pas été envoyée et donne-lui : {self._coordonnees()}."
        if not self.transmission_possible():
            return echec
        if not resume:
            return "Non transmis : le résumé de la demande est manquant."
        if not contact:
            return "Non transmis : demande d'abord au visiteur un courriel ou un numéro de téléphone pour le joindre."
        if self._transmissions >= MAX_TRANSMISSIONS_PAR_SESSION:
            return echec
        cle, aujourdhui = self.config.get("id") or self.config["nom_entreprise"], time.strftime("%Y-%m-%d")
        with _VERROU:
            jour, nombre = _TRANSMISSIONS_JOUR.get(cle, [aujourdhui, 0])
            if jour != aujourdhui:
                jour, nombre = aujourdhui, 0
            if nombre >= MAX_TRANSMISSIONS_PAR_JOUR:
                return echec
            _TRANSMISSIONS_JOUR[cle] = [jour, nombre + 1]

        urgente = str(priorite or "").lower().startswith(("urg", "high"))
        etiquette = "URGENTE" if urgente else "normale"
        extrait = "\n".join(
            f"{'Visiteur' if h['role'] == 'user' else 'NexBot'} : {h['text']}" for h in self.historique[-6:]
        )
        extrait += f"\nVisiteur : {self._message_courant}"
        corps = (
            f"Nouvelle demande reçue par l'assistant virtuel de {self.config['nom_entreprise']}\n"
            f"{'=' * 50}\n"
            f"Priorité : {etiquette}\n"
            f"Nom : {nom or '(non fourni)'}\n"
            f"Pour le joindre : {contact}\n"
            f"Langue du visiteur : {'anglais' if self.langue == 'en' else 'français'}\n"
            f"Date : {time.strftime('%Y-%m-%d %H:%M')} (heure du serveur)\n\n"
            f"Résumé :\n{resume}\n\n"
            f"Extrait de la conversation :\n{extrait}\n\n"
            f"--\nEnvoyé automatiquement par NexBot. Le visiteur a accepté d'être contacté. "
            f"Répondez directement à la personne avec les coordonnées ci-dessus."
        )
        trouve = _REGEX_COURRIEL.search(contact)
        try:
            envoyer_courriel(
                self.config["courriel_equipe"].strip(),
                f"[NexBot] Demande {etiquette} — {self.config['nom_entreprise']}",
                corps,
                repondre_a=trouve.group(0) if trouve else "",
            )
        except Exception as erreur:
            with _VERROU:
                jour, nombre = _TRANSMISSIONS_JOUR.get(cle, [aujourdhui, 1])
                _TRANSMISSIONS_JOUR[cle] = [jour, max(0, nombre - 1)]
            print(f"[erreur] Envoi du courriel impossible : {erreur}")
            return echec
        self._transmissions += 1
        self._transmis_ce_tour = True
        return "Transmis avec succès à l'équipe. Confirme-le au visiteur et dis-lui que l'équipe le contactera."

    # ---------- Plans Pro et Business : Gemini ----------
    def _instructions(self, avec_transmission: bool = False) -> str:
        c = self.config
        faq = "\n".join(
            f"- Q ({', '.join(e['mots_cles'] + e.get('mots_cles_en', []))}) : {e['reponse']}"
            + (f" / EN: {e['reponse_en']}" if e.get("reponse_en") else "")
            for e in c.get("faq", [])
        )
        morceaux = [
            f"Tu es l'assistant virtuel de l'entreprise « {c['nom_entreprise']} ».",
            "Langues : tu es bilingue. Réponds toujours dans la langue du dernier message "
            "du visiteur : français ou anglais. S'il écrit en anglais, réponds en anglais; "
            "s'il écrit en français, réponds en " + c.get("langue", "français québécois") + ". "
            "S'il change de langue, change aussi. Si le message est ambigu, utilise la langue "
            f"de la conversation (actuellement : {'anglais' if self.langue == 'en' else 'français'}). "
            "Les informations ci-dessous peuvent être en français : traduis-les fidèlement, sans rien inventer.",
            f"Ton : {c.get('ton', 'professionnel et chaleureux')}.",
            f"Heures d'ouverture : {c.get('heures', 'non précisées')}.",
        ]
        if c.get("infos"):
            morceaux.append(f"Informations sur l'entreprise :\n{c['infos']}")
        if faq:
            morceaux.append(f"Questions fréquentes :\n{faq}")
        if c.get("sujets_interdits"):
            morceaux.append(
                "Sujets interdits : ne réponds jamais aux questions portant sur "
                f"{c['sujets_interdits']}. Dis poliment que tu ne peux pas en parler "
                "et invite le visiteur à contacter l'entreprise directement."
            )
        if self.plan == "business" and c.get("personnalite"):
            morceaux.append(
                f"Personnalité de marque (à respecter dans chaque réponse) :\n{c['personnalite']}"
            )
        if avec_transmission:
            morceaux.append(
                "Transmission à l'équipe : tu disposes de l'outil transmettre_a_l_equipe qui envoie "
                "réellement un courriel à l'équipe. Utilise-le quand la demande exige un humain "
                "(urgence, plainte, demande hors de ta portée) ou quand le visiteur veut être contacté. "
                "Procédure : 1) propose de transmettre la demande; 2) obtiens son accord; 3) demande son "
                "nom et un courriel ou un téléphone; 4) appelle l'outil avec un résumé clair, la priorité "
                "(« urgente » seulement si c'est vraiment pressant, sinon « normale »), le nom et le contact. "
                "Ne dis JAMAIS que la demande est transmise avant que l'outil ait répondu « Transmis avec succès ». "
                f"Si l'outil échoue, dis-le honnêtement et donne : {self._coordonnees()}."
            )
        else:
            morceaux.append(
                "Transmission : tu ne peux PAS transmettre de demande ni recueillir de coordonnées. "
                "Ne le propose jamais et ne prétends jamais l'avoir fait. Quand une personne est nécessaire, "
                f"invite le visiteur à contacter l'équipe directement : {self._coordonnees()}."
            )
        morceaux.append(
            "Règles : réponds court et clair. Utilise seulement les informations "
            "ci-dessus. Si tu ne sais pas, dis-le honnêtement et propose de "
            "contacter l'équipe. N'invente jamais un prix, une heure ou une politique. "
            "Si on te demande, dis que tu es un assistant virtuel. "
            "Ne traduis jamais les noms propres, les noms de plans ni les adresses courriel."
        )
        return "\n\n".join(morceaux)

    def _repondre_gemini(self, message: str) -> str:
        from google import genai
        from google.genai import types

        global _CLIENT_GEMINI
        if _CLIENT_GEMINI is None:
            _CLIENT_GEMINI = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

        contenu = [
            types.Content(role=h["role"], parts=[types.Part(text=h["text"])])
            for h in self.historique
        ]
        contenu.append(types.Content(role="user", parts=[types.Part(text=message)]))

        def appeler(avec_outil: bool):
            options = dict(
                system_instruction=self._instructions(avec_outil),
                max_output_tokens=int(self.config.get("max_tokens", 400)),
            )
            if avec_outil:
                def transmettre_a_l_equipe(resume: str, priorite: str, nom: str, contact: str) -> str:
                    """Envoie par courriel la demande du visiteur à l'équipe de l'entreprise.
                    resume: résumé clair de la demande. priorite: « urgente » ou « normale ».
                    nom: nom du visiteur. contact: courriel ou téléphone du visiteur."""
                    return self._transmettre(resume, priorite, nom, contact)

                options["tools"] = [transmettre_a_l_equipe]
                options["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
                    maximum_remote_calls=3
                )
            return _CLIENT_GEMINI.models.generate_content(
                model=MODELE_GEMINI, contents=contenu, config=types.GenerateContentConfig(**options)
            )

        if self.transmission_possible():
            try:
                reponse = appeler(True)
            except (TypeError, ValueError, AttributeError) as erreur:  # outil refusé par la bibliothèque
                print(f"[avertissement] Outil de transmission indisponible : {erreur}")
                reponse = appeler(False)
        else:
            reponse = appeler(False)
        texte = (reponse.text or "").strip()
        if not texte:
            raise RuntimeError("Réponse vide de Gemini")
        return texte

    # ---------- Mémoire et limites ----------
    def _memoriser(self, message: str, reponse: str) -> None:
        max_echanges = MEMOIRE_ECHANGES[self.plan]
        if max_echanges == 0:
            return
        self.historique.append({"role": "user", "text": message})
        self.historique.append({"role": "model", "text": reponse})
        self.historique = self.historique[-max_echanges * 2:]

    def _limite_atteinte(self) -> bool:
        """Protège la facture Gemini avec un compteur conservé après redémarrage."""
        limite = int(self.config.get("limite_messages_jour", 200))
        cle = self.config.get("id") or self.config["nom_entreprise"]
        aujourdhui = time.strftime("%Y-%m-%d")
        with _VERROU:
            if not _COMPTEURS:
                try:
                    data = json.loads(_FICHIER_COMPTEURS.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        _COMPTEURS.update(data)
                except (FileNotFoundError, json.JSONDecodeError, OSError):
                    pass
            jour, nombre = _COMPTEURS.get(cle, [aujourdhui, 0])
            if jour != aujourdhui:
                jour, nombre = aujourdhui, 0
            nombre += 1
            _COMPTEURS[cle] = [jour, nombre]
            try:
                temporaire = _FICHIER_COMPTEURS.with_suffix(".tmp")
                temporaire.write_text(json.dumps(_COMPTEURS, ensure_ascii=False), encoding="utf-8")
                temporaire.replace(_FICHIER_COMPTEURS)
            except OSError:
                pass
        return nombre > limite
