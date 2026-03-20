import json
import os

import requests
from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///flashcards.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


class Flashcard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(255), nullable=False)
    answer = db.Column(db.String(255), nullable=False)


def generate_flashcards_from_notes(notes: str):
    """Call an AI API and return a validated flashcard JSON list.

    Expected return format:
    [
      {"question": "...", "answer": "..."},
      ...
    ]
    """
    if not notes or not notes.strip():
        raise ValueError("notes must be a non-empty string")

    api_url = os.getenv("AI_API_URL", "https://api.openai.com/v1/chat/completions")
    api_key = os.getenv("AI_API_KEY")
    model = os.getenv("AI_MODEL", "gpt-4.1-mini")

    if not api_key:
        raise RuntimeError("Missing AI_API_KEY environment variable")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    prompt = (
        "Generate flashcards from these study notes. "
        "Return only valid JSON as an array of objects with exactly two keys: "
        "question and answer."
    )

    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You create concise study flashcards. "
                    "Output strict JSON only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\n"
                    "Return shape: {\"flashcards\": [{\"question\": \"...\", \"answer\": \"...\"}]}\n\n"
                    f"Notes:\n{notes}"
                ),
            },
        ],
    }

    response = requests.post(api_url, headers=headers, json=payload, timeout=45)
    response.raise_for_status()
    data = response.json()

    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        raise RuntimeError("AI response did not contain message content")

    parsed = json.loads(content)
    flashcards = parsed.get("flashcards") if isinstance(parsed, dict) else parsed

    if not isinstance(flashcards, list):
        raise ValueError("AI response JSON must include a flashcards list")

    validated = []
    for card in flashcards:
        if not isinstance(card, dict):
            continue
        question = str(card.get("question", "")).strip()
        answer = str(card.get("answer", "")).strip()
        if question and answer:
            validated.append({"question": question, "answer": answer})

    if not validated:
        raise ValueError("No valid flashcards found in AI response")

    return validated


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/submit")
def submit():
    # Placeholder for future form processing logic.
    form_data = request.form.to_dict()
    return {
        "message": "Form received",
        "data": form_data,
    }, 200


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
