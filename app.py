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
