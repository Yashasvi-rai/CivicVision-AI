import numpy as np
from flask import Flask, request, jsonify
from PIL import Image
from tensorflow.keras.models import load_model

app = Flask(__name__)

# LOAD MODEL
model = load_model("model.keras")

# ⚠️ MUST MATCH YOUR DATASET (you had 3 classes)
classes = ["garbage", "pothole", "drainage"]

def preprocess_image(image):
    image = image.resize((224, 224))
    image = np.array(image) / 255.0
    image = np.expand_dims(image, axis=0)
    return image

@app.route("/")
def home():
    return "API is running"

@app.route("/predict", methods=["POST"])
def predict():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]

    image = Image.open(file).convert("RGB")
    processed = preprocess_image(image)

    prediction = model.predict(processed)
    class_index = int(np.argmax(prediction))
    confidence = float(np.max(prediction))

    return jsonify({
        "class": classes[class_index],
        "confidence": round(confidence, 3)
    })

if __name__ == "__main__":
    app.run(port=5000, debug=True)