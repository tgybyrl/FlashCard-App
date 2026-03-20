import json
import os

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy

load_dotenv()

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

    # Some OpenAI-compatible providers do not support response_format.
    if os.getenv("AI_USE_RESPONSE_FORMAT", "false").lower() == "true":
        payload["response_format"] = {"type": "json_object"}

    response = requests.post(api_url, headers=headers, json=payload, timeout=45)
    if not response.ok:
        provider_error = response.text[:500]
        raise RuntimeError(
            f"AI request failed ({response.status_code}) at {api_url}: {provider_error}"
        )
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
    return render_template(
        "index.html",
        flashcards=[],
        notes_text="",
        error=None,
        success=None,
    )


@app.post("/submit")
def submit():
    notes = request.form.get("notes", "").strip()

    if not notes:
        return (
            render_template(
                "index.html",
                flashcards=[],
                notes_text="",
                error="Please paste some notes first.",
                success=None,
            ),
            400,
        )

    try:
        generated_cards = generate_flashcards_from_notes(notes)

        saved_cards = []
        for card in generated_cards:
            flashcard = Flashcard(
                question=card["question"],
                answer=card["answer"],
            )
            db.session.add(flashcard)
            saved_cards.append(flashcard)

        db.session.commit()

        return render_template(
            "index.html",
            flashcards=saved_cards,
            notes_text=notes,
            error=None,
            success=f"Generated and saved {len(saved_cards)} flashcards.",
        )
    except Exception as exc:
        db.session.rollback()
        return (
            render_template(
                "index.html",
                flashcards=[],
                notes_text=notes,
                error=f"Could not generate flashcards: {exc}",
                success=None,
            ),
            500,
        )


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
