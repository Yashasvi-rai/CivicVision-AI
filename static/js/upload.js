// =====================================
// Urban Vision AI - Upload Module
// =====================================

console.log("upload.js loaded");

document.addEventListener("DOMContentLoaded", function () {

    const uploadForm =
        document.getElementById("uploadForm");

    const fileInput =
        document.getElementById("file");

    const preview =
        document.getElementById("preview");

    const dropZone =
        document.querySelector(".drop-zone");

    if (!uploadForm || !fileInput) {
        return;
    }

    // ===============================
    // Image Preview
    // ===============================

    fileInput.addEventListener(
        "change",
        function () {

            const file = this.files[0];

            if (!file) {
                return;
            }

            // Check image type
            if (!file.type.startsWith("image/")) {

                alert("Please select an image.");

                this.value = "";

                return;
            }

            // Check file size
            if (file.size > 10 * 1024 * 1024) {

                alert(
                    "Maximum image size is 10 MB."
                );

                this.value = "";

                return;
            }

            // Show preview
            if (preview) {

                const reader =
                    new FileReader();

                reader.onload =
                    function (e) {

                        preview.src =
                            e.target.result;

                        preview.style.display =
                            "block";
                    };

                reader.readAsDataURL(file);
            }

        }
    );


    // ===============================
    // Drag & Drop
    // ===============================

    if (dropZone) {

        dropZone.addEventListener(
            "dragover",
            function (e) {

                e.preventDefault();

                dropZone.classList.add(
                    "border-primary"
                );

            }
        );


        dropZone.addEventListener(
            "dragleave",
            function () {

                dropZone.classList.remove(
                    "border-primary"
                );

            }
        );


        dropZone.addEventListener(
            "drop",
            function (e) {

                e.preventDefault();

                dropZone.classList.remove(
                    "border-primary"
                );

                const files =
                    e.dataTransfer.files;

                if (files.length === 0) {
                    return;
                }

                fileInput.files = files;

                fileInput.dispatchEvent(
                    new Event("change")
                );

            }
        );
    }


    // IMPORTANT:
    //
    // There is NO submit event here.
    //
    // prediction.js is the ONLY file that
    // handles the uploadForm submit event
    // and sends POST /predict.
    //
    // This prevents duplicate requests.


});


// =====================================
// GPS Location
// =====================================

document.addEventListener(
    "DOMContentLoaded",
    function () {

        const latInput =
            document.getElementById("lat");

        const lngInput =
            document.getElementById("lng");

        if (!latInput || !lngInput) {
            return;
        }

        if (!navigator.geolocation) {

            alert(
                "Geolocation not supported."
            );

            return;
        }


        navigator.geolocation.getCurrentPosition(

            function (position) {

                latInput.value =
                    position.coords.latitude;

                lngInput.value =
                    position.coords.longitude;

                console.log(
                    "Latitude:",
                    position.coords.latitude
                );

                console.log(
                    "Longitude:",
                    position.coords.longitude
                );

            },

            function (error) {

                console.log(
                    "Geolocation error:",
                    error
                );

                alert(
                    "Please allow location permission."
                );

            }

        );

    }
);