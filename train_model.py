import tensorflow as tf
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.applications import MobileNetV2
from tensorflow.keras import layers, models
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint

# =====================================
# SETTINGS
# =====================================

IMG_SIZE = (224, 224)
BATCH_SIZE = 32
EPOCHS = 20

TRAIN_DIR = "dataset/train"
VAL_DIR = "dataset/validation"
TEST_DIR = "dataset/test"

# =====================================
# DATA GENERATORS
# =====================================

train_datagen = ImageDataGenerator(
    rescale=1./255,
    rotation_range=20,
    zoom_range=0.2,
    width_shift_range=0.2,
    height_shift_range=0.2,
    horizontal_flip=True,
    fill_mode='nearest'
)

val_datagen = ImageDataGenerator(
    rescale=1./255
)

test_datagen = ImageDataGenerator(
    rescale=1./255
)

# =====================================
# TRAIN DATA
# =====================================

train_data = train_datagen.flow_from_directory(
    TRAIN_DIR,
    target_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    class_mode='categorical',
    shuffle=True
)

# =====================================
# VALIDATION DATA
# =====================================

val_data = val_datagen.flow_from_directory(
    VAL_DIR,
    target_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    class_mode='categorical',
    shuffle=False
)

# =====================================
# TEST DATA
# =====================================

test_data = test_datagen.flow_from_directory(
    TEST_DIR,
    target_size=IMG_SIZE,
    batch_size=BATCH_SIZE,
    class_mode='categorical',
    shuffle=False
)

print("\nClass Mapping:")
print(train_data.class_indices)

print("\nTraining Images:", train_data.samples)
print("Validation Images:", val_data.samples)
print("Test Images:", test_data.samples)

# =====================================
# MOBILENETV2
# =====================================

base_model = MobileNetV2(
    input_shape=(224, 224, 3),
    include_top=False,
    weights='imagenet'
)

base_model.trainable = False

# =====================================
# MODEL
# =====================================

model = models.Sequential([
    base_model,

    layers.GlobalAveragePooling2D(),

    layers.Dense(256, activation='relu'),

    layers.Dropout(0.4),

    layers.Dense(
        train_data.num_classes,
        activation='softmax'
    )
])

# =====================================
# COMPILE
# =====================================

model.compile(
    optimizer='adam',
    loss='categorical_crossentropy',
    metrics=['accuracy']
)

# =====================================
# CALLBACKS
# =====================================

early_stop = EarlyStopping(
    monitor='val_accuracy',
    patience=5,
    restore_best_weights=True,
    verbose=1
)

checkpoint = ModelCheckpoint(
    "best_model.h5",
    monitor='val_accuracy',
    save_best_only=True,
    verbose=1
)

# =====================================
# TRAIN
# =====================================

history = model.fit(
    train_data,
    validation_data=val_data,
    epochs=EPOCHS,
    callbacks=[early_stop, checkpoint]
)

# =====================================
# TEST ACCURACY
# =====================================

test_loss, test_accuracy = model.evaluate(test_data)

print(f"\nTest Accuracy: {test_accuracy:.4f}")
print(f"Test Loss: {test_loss:.4f}")

# =====================================
# SAVE MODEL
# =====================================

model.save("model.h5")

print("\n✅ Training Complete")
print("✅ Best model saved as best_model.h5")
print("✅ Final model saved as model.h5")