import json
import os
import base64
import time
import logging

import requests
from dotenv import load_dotenv
from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import RequestEntityTooLarge

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

app = Flask(__name__)
DEBUG_MODE = _env_flag("FLASK_DEBUG", True)
secret_key = os.getenv("SECRET_KEY", "").strip()
if not secret_key:
    if DEBUG_MODE:
        secret_key = "dev-change-me"
        logging.warning(
            "[flashard] SECRET_KEY is not set. Using development fallback key.",
        )
    else:
        raise RuntimeError(
            "SECRET_KEY must be set when FLASK_DEBUG is false. "
            "Set a long random SECRET_KEY in your environment."
        )
elif not DEBUG_MODE and secret_key == "dev-change-me":
    raise RuntimeError(
        "SECRET_KEY cannot use the default development value when FLASK_DEBUG is false."
    )

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///flashcards.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB upload limit
app.config["SECRET_KEY"] = secret_key
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = _env_flag("SESSION_COOKIE_SECURE", False)

ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "10"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
REQUEST_LOG_PREFIX = "[flashard]"

# Simple in-memory limiter for basic abuse control in single-process dev usage.
_submit_rate_limit_store: dict[str, list[float]] = {}

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
logging.basicConfig(level=logging.INFO)


class Flashcard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(255), nullable=False)
    answer = db.Column(db.String(255), nullable=False)


class AIServiceError(Exception):
    pass


def _detect_image_mime(image_bytes: bytes) -> str | None:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return None


def _is_rate_limited(client_ip: str) -> bool:
    now = time.time()
    recent = _submit_rate_limit_store.get(client_ip, [])
    recent = [ts for ts in recent if (now - ts) <= RATE_LIMIT_WINDOW_SECONDS]
    if len(recent) >= RATE_LIMIT_MAX_REQUESTS:
        _submit_rate_limit_store[client_ip] = recent
        return True
    recent.append(now)
    _submit_rate_limit_store[client_ip] = recent
    return False


def generate_flashcards_from_notes(notes: str, image_data_url: str | None = None):
    """Call an AI API and return a validated flashcard JSON list.

    Expected return format:
    [
      {"question": "...", "answer": "..."},
      ...
    ]
    """
    if not notes.strip() and not image_data_url:
        raise ValueError("Provide notes or an image")

    api_url = os.getenv("AI_API_URL", "https://api.openai.com/v1/chat/completions")
    api_key = os.getenv("AI_API_KEY")
    base_model = os.getenv("AI_MODEL", "gpt-4.1-mini")
    vision_model = os.getenv("AI_VISION_MODEL", "").strip()

    if image_data_url:
        if vision_model:
            model = vision_model
        elif "api.groq.com" in api_url:
            model = "meta-llama/llama-4-scout-17b-16e-instruct"
        else:
            model = base_model
    else:
        model = base_model

    if not api_key:
        raise AIServiceError("AI service is not configured yet.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    prompt = (
        "Generate flashcards from these study notes. "
        "Return only valid JSON as an array of objects with exactly two keys: "
        "question and answer."
    )

    user_text = (
        f"{prompt}\n\n"
        "Return shape: {\"flashcards\": [{\"question\": \"...\", \"answer\": \"...\"}]}\n\n"
        f"Notes:\n{notes or 'No text notes provided. Use the image content.'}"
    )

    if image_data_url:
        user_content = [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    else:
        user_content = user_text

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
                "content": user_content,
            },
        ],
    }

    # Some OpenAI-compatible providers do not support response_format.
    if os.getenv("AI_USE_RESPONSE_FORMAT", "false").lower() == "true":
        payload["response_format"] = {"type": "json_object"}

    response = requests.post(api_url, headers=headers, json=payload, timeout=45)
    if not response.ok:
        provider_error = response.text[:500]
        if image_data_url and "content must be a string" in provider_error:
            raise AIServiceError(
                "Your current model does not support image inputs. "
                "Set AI_VISION_MODEL to a vision-capable model."
            )
        app.logger.warning(
            "%s AI request failed status=%s endpoint=%s detail=%s",
            REQUEST_LOG_PREFIX,
            response.status_code,
            api_url,
            provider_error,
        )
        raise AIServiceError("AI provider request failed. Please try again.")
    data = response.json()

    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not content:
        raise AIServiceError("AI response was empty. Please try again.")

    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        app.logger.warning(
            "%s Invalid JSON from AI: %s",
            REQUEST_LOG_PREFIX,
            exc,
        )
        raise AIServiceError("AI returned invalid format. Please try again.") from exc
    flashcards = parsed.get("flashcards") if isinstance(parsed, dict) else parsed

    if not isinstance(flashcards, list):
        raise AIServiceError("AI response did not contain flashcards.")

    validated = []
    for card in flashcards:
        if not isinstance(card, dict):
            continue
        question = str(card.get("question", "")).strip()
        answer = str(card.get("answer", "")).strip()
        if question and answer:
            validated.append({"question": question, "answer": answer})

    if not validated:
        raise AIServiceError("No valid flashcards could be generated.")

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
    uploaded_photo = request.files.get("photo")
    image_data_url = None
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")

    if _is_rate_limited(client_ip):
        return (
            render_template(
                "index.html",
                flashcards=[],
                notes_text=notes,
                error="Too many requests. Please wait a minute and try again.",
                success=None,
            ),
            429,
        )

    has_photo = bool(uploaded_photo and uploaded_photo.filename)

    if not notes and not has_photo:
        return (
            render_template(
                "index.html",
                flashcards=[],
                notes_text="",
                error="Please paste notes or upload an image first.",
                success=None,
            ),
            400,
        )

    if has_photo:
        mime_type = uploaded_photo.mimetype
        if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
            return (
                render_template(
                    "index.html",
                    flashcards=[],
                    notes_text=notes,
                    error="Unsupported image type. Use JPG, PNG, or WEBP.",
                    success=None,
                ),
                400,
            )

        image_bytes = uploaded_photo.read()
        if not image_bytes:
            return (
                render_template(
                    "index.html",
                    flashcards=[],
                    notes_text=notes,
                    error="Uploaded image is empty.",
                    success=None,
                ),
                400,
            )

        actual_mime_type = _detect_image_mime(image_bytes)
        if actual_mime_type != mime_type:
            return (
                render_template(
                    "index.html",
                    flashcards=[],
                    notes_text=notes,
                    error="Uploaded image content does not match file type.",
                    success=None,
                ),
                400,
            )

        encoded_image = base64.b64encode(image_bytes).decode("utf-8")
        image_data_url = f"data:{mime_type};base64,{encoded_image}"

    try:
        generated_cards = generate_flashcards_from_notes(notes, image_data_url)

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
    except AIServiceError as exc:
        db.session.rollback()
        return (
            render_template(
                "index.html",
                flashcards=[],
                notes_text=notes,
                error=str(exc),
                success=None,
            ),
            502,
        )
    except Exception:
        db.session.rollback()
        app.logger.exception("%s Unexpected submit error", REQUEST_LOG_PREFIX)
        return (
            render_template(
                "index.html",
                flashcards=[],
                notes_text=notes,
                error="Something went wrong while generating flashcards. Please try again.",
                success=None,
            ),
            500,
        )


@app.post("/regenerate")
def regenerate():
    notes = request.form.get("notes", "").strip()
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")

    if _is_rate_limited(client_ip):
        existing_cards = Flashcard.query.order_by(Flashcard.id.asc()).all()
        return (
            render_template(
                "index.html",
                flashcards=existing_cards,
                notes_text=notes,
                error="Too many requests. Please wait a minute and try again.",
                success=None,
            ),
            429,
        )

    if not notes:
        existing_cards = Flashcard.query.order_by(Flashcard.id.asc()).all()
        return (
            render_template(
                "index.html",
                flashcards=existing_cards,
                notes_text="",
                error="Please paste notes before regenerating flashcards.",
                success=None,
            ),
            400,
        )

    try:
        generated_cards = generate_flashcards_from_notes(notes, None)

        Flashcard.query.delete()

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
            success=f"Regenerated and replaced with {len(saved_cards)} flashcards.",
        )
    except AIServiceError as exc:
        db.session.rollback()
        existing_cards = Flashcard.query.order_by(Flashcard.id.asc()).all()
        return (
            render_template(
                "index.html",
                flashcards=existing_cards,
                notes_text=notes,
                error=str(exc),
                success=None,
            ),
            502,
        )
    except Exception:
        db.session.rollback()
        app.logger.exception("%s Unexpected regenerate error", REQUEST_LOG_PREFIX)
        existing_cards = Flashcard.query.order_by(Flashcard.id.asc()).all()
        return (
            render_template(
                "index.html",
                flashcards=existing_cards,
                notes_text=notes,
                error="Something went wrong while regenerating flashcards. Please try again.",
                success=None,
            ),
            500,
        )


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(_error):
    return (
        render_template(
            "index.html",
            flashcards=[],
            notes_text="",
            error="File is too large. Max upload size is 4MB.",
            success=None,
        ),
        413,
    )


@app.errorhandler(CSRFError)
def handle_csrf_error(_error):
    notes = request.form.get("notes", "").strip()
    return (
        render_template(
            "index.html",
            flashcards=[],
            notes_text=notes,
            error="Your session expired or the form is invalid. Please refresh and try again.",
            success=None,
        ),
        400,
    )


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=DEBUG_MODE)
