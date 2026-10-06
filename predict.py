import tensorflow as tf
import numpy as np
from tensorflow.keras.preprocessing import image

# Load trained model
model = tf.keras.models.load_model("C:/Users/yasha/Documents/main_project/model.keras")

# Class labels (must match training)
class_names = ['drainage_issue', 'garbage', 'pothole']

def predict_image(img_path):
    img = image.load_img(img_path, target_size=(224,224))
    img_array = image.img_to_array(img)/255.0
    img_array = np.expand_dims(img_array, axis=0)

    pred = model.predict(img_array)

    pred_class = np.argmax(pred)
    confidence = np.max(pred)

    if confidence < 0.7:
        return "Unknown", confidence
    else:
        return class_names[pred_class], confidence


# Test run
if __name__ == "__main__":
    img_path = "C:/Users/yasha/Documents/main_project/urban_issue_dataset/pothole/48.jpg"

    label, conf = predict_image(img_path)

    print("Prediction:", label)
    print("Confidence: {:.2f}%".format(conf * 100))