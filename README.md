# Jarvis test

ChatGPT parle. Claude exécute.

Le lien GitHub affiche la page, mais n'appelle pas les API : une clé dans la page serait publique, et les API bloquent le navigateur.

Sur un ordinateur :

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
python3 server.py
```

Puis ouvre http://127.0.0.1:8787

Les clés peuvent aussi être collées dans la page : elles restent dans la session du navigateur et partent seulement vers ce serveur local.
