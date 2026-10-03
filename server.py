#!/usr/bin/env python3
"""Jarvis proxy. ChatGPT parle. Claude exécute. Les clés ne sont jamais écrites sur disque."""

import json
import os
import threading
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TALK_MODEL = os.environ.get("JARVIS_TALK_MODEL", "gpt-4.1-mini")
ACT_MODEL = os.environ.get("JARVIS_ACT_MODEL", "claude-sonnet-4-6")

TOOLS = [
    {
        "name": "resume_mails",
        "description": "Résume les mails urgents. Indépendant, peut partir en parallèle.",
        "input_schema": {"type": "object", "properties": {"filtre": {"type": "string"}}, "required": []},
    },
    {
        "name": "creer_rappel",
        "description": "Crée un rappel. Indépendant.",
        "input_schema": {
            "type": "object",
            "properties": {"quand": {"type": "string"}, "sujet": {"type": "string"}},
            "required": ["quand", "sujet"],
        },
    },
    {
        "name": "chercher",
        "description": "Recherche une info (prix, fait). À lancer avant une rédaction qui en dépend.",
        "input_schema": {"type": "object", "properties": {"requete": {"type": "string"}}, "required": ["requete"]},
    },
    {
        "name": "ecrire",
        "description": "Écrit un brouillon, script ou message. Ne l'envoie pas.",
        "input_schema": {
            "type": "object",
            "properties": {"type": {"type": "string"}, "brief": {"type": "string"}, "avec": {"type": "string"}},
            "required": ["brief"],
        },
    },
    {
        "name": "envoyer",
        "description": "Envoie un message. Refuser sans confirmation explicite de l'utilisateur.",
        "input_schema": {
            "type": "object",
            "properties": {"destinataire": {"type": "string"}, "contenu": {"type": "string"}, "confirme": {"type": "boolean"}},
            "required": ["destinataire"],
        },
    },
]

BOARD = []
LOCK = threading.Lock()


def post(url, headers, payload, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()[:500]
        raise RuntimeError(f"{exc.code} {body}") from exc


def run_tool(name, args):
    args = args or {}
    if name == "resume_mails":
        result = "2 urgents — facture KiDi+ et relance Zembo."
    elif name == "creer_rappel":
        result = f"rappel créé : {args.get('sujet', 'sans sujet')} · {args.get('quand', 'non daté')}."
    elif name == "chercher":
        result = f"trouvé pour « {args.get('requete', '')} » : forfait à 19 $/mois."
    elif name == "ecrire":
        result = f"brouillon prêt ({args.get('type', 'texte')}) : {args.get('brief', '')[:180]}"
    elif name == "envoyer":
        if not args.get("confirme"):
            result = "bloqué — confirmation requise avant envoi."
        else:
            result = f"envoyé à {args.get('destinataire', 'destinataire manquant')}."
    else:
        result = "outil inconnu."
    with LOCK:
        BOARD.append({"tool": name, "result": result})
    return result


def act(key, text):
    system = (
        "Tu es le moteur d'action de Jarvis. Découpe la dictée en tâches. "
        "Appelle en parallèle, dans le même tour, les outils indépendants. "
        "N'appelle ecrire qu'après chercher si le texte dépend du prix. "
        "N'envoie jamais sans confirme=true. Réponds en français, court, après les outils."
    )
    messages = [{"role": "user", "content": text}]
    steps = []
    for _ in range(4):
        data = post(
            ANTHROPIC_URL,
            {
                "content-type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
            {
                "model": ACT_MODEL,
                "max_tokens": 1200,
                "system": system,
                "tools": TOOLS,
                "messages": messages,
            },
        )
        content = data.get("content") or []
        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        texts = [b.get("text", "") for b in content if b.get("type") == "text"]
        if not tool_uses:
            return {"model": ACT_MODEL, "steps": steps, "summary": " ".join(texts).strip()}
        results = []
        for block in tool_uses:
            out = run_tool(block.get("name"), block.get("input"))
            steps.append({"tool": block.get("name"), "input": block.get("input"), "result": out})
            results.append({"type": "tool_result", "tool_use_id": block.get("id"), "content": out})
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": results})
    return {"model": ACT_MODEL, "steps": steps, "summary": "Tour d'outils terminé."}


def talk(key, text, context=""):
    prompt = (
        "Tu es la voix de Jarvis. Français oral, phrases courtes, aucun pavé. "
        "Dis ce qui est fait. Une ligne de statut, puis un résultat par tâche. "
        "Pas de 'je vais'."
    )
    user = text if not context else f"Dictée : {text}\nTravail de Claude : {context}\nDis le résultat à voix haute."
    data = post(
        OPENAI_URL,
        {"content-type": "application/json", "authorization": f"Bearer {key}"},
        {
            "model": TALK_MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user},
            ],
        },
    )
    reply = data["choices"][0]["message"]["content"].strip()
    return {"model": TALK_MODEL, "reply": reply}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("cache-control", "no-store")
        super().end_headers()

    def send_json(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        n = int(self.headers.get("content-length") or 0)
        if n > 100_000:
            raise ValueError("requête trop grande")
        return json.loads(self.rfile.read(n).decode() or "{}")

    def do_GET(self):
        if self.path.startswith("/api/health"):
            self.send_json(200, {"ok": True, "talk": TALK_MODEL, "act": ACT_MODEL})
            return
        if self.path in ("/", ""):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        try:
            body = self.read_json()
            text = (body.get("text") or "").strip()
            if not text:
                self.send_json(400, {"error": "texte vide"})
                return
            if self.path.startswith("/api/act"):
                key = self.headers.get("x-anthropic-key") or os.environ.get("ANTHROPIC_API_KEY")
                if not key:
                    self.send_json(401, {"error": "clé Claude manquante"})
                    return
                self.send_json(200, act(key, text))
                return
            if self.path.startswith("/api/talk"):
                key = self.headers.get("x-openai-key") or os.environ.get("OPENAI_API_KEY")
                if not key:
                    self.send_json(401, {"error": "clé ChatGPT manquante"})
                    return
                self.send_json(200, talk(key, text, body.get("context") or ""))
                return
            self.send_json(404, {"error": "route inconnue"})
        except Exception as exc:
            self.send_json(502, {"error": str(exc)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8787"))
    print(f"Jarvis sur http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
