"""Tester un bot dans le terminal :  python run.py clients/clinique_exemple.json"""
import sys

from bot import Bot, charger_client

if len(sys.argv) != 2:
    sys.exit("Usage : python run.py clients/<fichier>.json")

config = charger_client(sys.argv[1])
bot = Bot(config)

print(f"=== {config['nom_entreprise']} — plan {config['plan']} (tape 'quitter' pour arrêter) ===")
print(config.get("message_accueil", "Bonjour! Comment puis-je vous aider?"))

while True:
    question = input("\nClient : ").strip()
    if question.lower() in ("quitter", "exit", "q"):
        break
    if question:
        print(f"Bot    : {bot.repondre(question)}")
