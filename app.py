from flask import Flask, render_template, request

app = Flask(__name__)


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
    app.run(debug=True)
