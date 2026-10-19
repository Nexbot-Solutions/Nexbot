"""Moteur unique pour les 3 plans : Essentiel, Pro, Business.

Un seul code. Ce qui change d'un client à l'autre, c'est son fichier
de configuration JSON dans le dossier clients/.
"""
import json
import os
import re
import threading
import time
import unicodedata
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

        if self.plan == "essentiel":
            reponse = self._repondre_mots_cles(message)
        else:
            try:
                reponse = self._repondre_gemini(message)
            except Exception as erreur:  # panne réseau, clé invalide, quota...
                print(f"[avertissement] Gemini indisponible : {erreur}")
                reponse = self._repondre_mots_cles(message)

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

    # ---------- Plans Pro et Business : Gemini ----------
    def _instructions(self) -> str:
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
        if self.plan == "business" and c.get("personnalite"):
            morceaux.append(
                f"Personnalité de marque (à respecter dans chaque réponse) :\n{c['personnalite']}"
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

        reponse = _CLIENT_GEMINI.models.generate_content(
            model=MODELE_GEMINI,
            contents=contenu,
            config=types.GenerateContentConfig(
                system_instruction=self._instructions(),
                max_output_tokens=int(self.config.get("max_tokens", 400)),
            ),
        )
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
