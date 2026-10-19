"""Créer un nouveau client à partir du modèle.

Exemple :
  python nouveau_client.py --id clinique-abc --nom "Clinique ABC" --plan pro --domaine cliniqueabc.com

Crée clients/clinique-abc.json, puis affiche la ligne à donner au client
pour son site web. Ouvre ensuite le fichier pour remplir la FAQ et les infos.
"""
import argparse
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(description="Créer un nouveau client")
parser.add_argument("--id", required=True, help="identifiant sans espaces, ex. clinique-abc")
parser.add_argument("--nom", required=True, help="nom de l'entreprise")
parser.add_argument("--plan", required=True, choices=["essentiel", "pro", "business"])
parser.add_argument("--domaine", action="append", default=[], help="site du client (répétable), ex. cliniqueabc.com")
parser.add_argument("--courriel-equipe", default="", help="courriel qui reçoit les demandes transmises par le bot (plans Pro et Business)")
parser.add_argument("--serveur", default="https://TON-SERVEUR", help="adresse publique de ton serveur")
args = parser.parse_args()

if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", args.id):
    sys.exit("L'identifiant doit contenir seulement a-z, 0-9 et tirets (ex. clinique-abc).")

destination = BASE / "clients" / f"{args.id}.json"
if destination.exists():
    sys.exit(f"{destination.name} existe déjà. Choisis un autre identifiant.")

config = json.loads((BASE / "clients" / "_modele.json").read_text(encoding="utf-8"))
config["id"] = args.id
config["nom_entreprise"] = args.nom
config["plan"] = args.plan
config["courriel_equipe"] = args.courriel_equipe
config["domaines_autorises"] = [d.lower().replace("https://", "").replace("http://", "").strip("/") for d in args.domaine]
destination.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(f"Client créé : {destination}")
print("\n1) Ouvre ce fichier et remplis la FAQ, les heures et les infos de l'entreprise.")
print("2) Redémarre le serveur (ou redéploie) pour qu'il charge le client.")
print("3) Donne cette ligne au client, à coller avant </body> sur son site :\n")
print(f'<script src="{args.serveur}/widget.js" data-client="{args.id}" async></script>')
if args.plan != "essentiel" and not args.courriel_equipe:
    print("\nAttention : aucun --courriel-equipe. Le bot ne pourra pas transmettre de demandes : il invitera le visiteur à contacter l'entreprise directement (champ coordonnees_humain).")
if not config["domaines_autorises"]:
    print("\nAttention : aucun --domaine précisé, le bot est utilisable depuis n'importe quel site.")
