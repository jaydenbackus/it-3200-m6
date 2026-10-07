from flask import Flask, render_template

app = Flask(__name__)

STUDENT = {
    "name": "Jayden Backus",
    "student_id": "11005564",
    "course": "IT 3200",
}


@app.route("/")
def index():
    return render_template("index.html", **STUDENT)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
