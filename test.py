from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
import numpy as np

model = load_model("urban_issue_model.h5")

img_path = "test.jpg"  # put any test image here

img = image.load_img(img_path, target_size=(224,224))
img_array = image.img_to_array(img)
img_array = np.expand_dims(img_array, axis=0) / 255.0

prediction = model.predict(img_array)

classes = ["drainage_issue", "garbage", "pothole", "streetlight"]

print("Prediction:", classes[np.argmax(prediction)])