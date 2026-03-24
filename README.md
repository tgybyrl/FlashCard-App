# AI Flashcard Generator

A Python Flask backend that converts study notes and optional uploaded images into flashcards using an AI provider API.

## Features

- Generate flashcards from plain text notes
- Optional image upload support for vision-capable models
- Structured flashcard output with question and answer fields
- SQLite persistence using Flask-SQLAlchemy
- Basic security hardening:
  - Environment-based secrets and config
  - CSRF protection on POST forms
  - File size/type validation for uploads
  - Generic user-safe error responses
  - Simple rate limiting on generation requests

## Tech Stack

- Python 3
- Flask
- Flask-SQLAlchemy
- Flask-WTF
- SQLite
- Requests
- Python-Dotenv

## Installation

### 1. Clone the repository

Use your repository URL:

git clone <your-repo-url>
cd <your-project-folder>

### 2. Create and activate a virtual environment

Windows PowerShell:

python -m venv .venv
.\.venv\Scripts\Activate.ps1

### 3. Install dependencies

pip install flask flask-sqlalchemy flask-wtf requests python-dotenv

### 4. Configure environment variables

Create a local .env file in the project root (do not commit this file):

AI_API_KEY=your_api_key_here
AI_API_URL=https://api.groq.com/openai/v1/chat/completions
AI_MODEL=llama-3.1-8b-instant
AI_VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
AI_USE_RESPONSE_FORMAT=false
FLASK_DEBUG=true
SECRET_KEY=replace_with_long_random_secret
SESSION_COOKIE_SECURE=false
RATE_LIMIT_MAX_REQUESTS=10
RATE_LIMIT_WINDOW_SECONDS=60

### 5. Run the application

python .\app.py

The app will start on:

http://127.0.0.1:5000

## API Endpoints

### GET /

Renders the main web interface for submitting notes and/or an image.

Response:

- 200 OK
- HTML page

### POST /submit

Generates flashcards from submitted text and optional image input, then stores generated flashcards in SQLite.

Form fields:

- notes: string (optional if photo is provided)
- photo: image file (optional if notes are provided)

Success response:

- 200 OK
- HTML page with generated flashcards

Validation and error responses:

- 400 Bad Request: invalid input (no notes/photo, invalid file type, empty file)
- 400 Bad Request: invalid/missing CSRF token on protected form submissions
- 413 Payload Too Large: upload exceeds configured size limit
- 429 Too Many Requests: rate limit reached
- 502 Bad Gateway: AI service returned a recoverable provider error
- 500 Internal Server Error: unexpected server error

## Notes

- Keep production secrets only in environment variables.
- Set FLASK_DEBUG=false and SESSION_COOKIE_SECURE=true in production.
- When FLASK_DEBUG=false, SECRET_KEY must be explicitly set and cannot use the default development placeholder value.
- Rotate API keys immediately if they are ever exposed.
