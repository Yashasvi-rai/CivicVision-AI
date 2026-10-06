// =======================================
// Urban Vision AI - Prediction Module
// =======================================

document.addEventListener("DOMContentLoaded", function () {

    const form = document.getElementById("uploadForm");

    if (!form) {
        console.log("uploadForm not found");
        return;
    }

    // Prevent duplicate event handler
    if (form.dataset.predictionHandlerBound === "true") {
        console.log("Prediction handler already attached.");
        return;
    }

    form.dataset.predictionHandlerBound = "true";

    // Prevent duplicate /predict requests
    let predictionSubmitting = false;

    form.addEventListener("submit", async function (e) {

        e.preventDefault();
        e.stopPropagation();

        // ==========================================
        // PREVENT DUPLICATE SUBMISSION
        // ==========================================

        if (predictionSubmitting) {

            console.log(
                "Duplicate submit ignored - prediction already running."
            );

            return;
        }

        console.log("Prediction button clicked");

        // ==========================================
        // GET LOCATION MODE
        // ==========================================

        const locationModeElement =
            document.getElementById("location_mode");

        const manualAddressElement =
            document.getElementById("manual_address");

        const latElement =
            document.getElementById("lat");

        const lngElement =
            document.getElementById("lng");

        const locationMode =
            locationModeElement
                ? locationModeElement.value
                : "auto";

        const manualAddress =
            manualAddressElement
                ? manualAddressElement.value.trim()
                : "";

        const lat =
            latElement
                ? latElement.value.trim()
                : "";

        const lng =
            lngElement
                ? lngElement.value.trim()
                : "";

        console.log("Location mode:", locationMode);
        console.log("Manual address:", manualAddress);
        console.log("Latitude:", lat);
        console.log("Longitude:", lng);

        // ==========================================
        // VALIDATE LOCATION
        // ==========================================

        /*
         * AUTO / GPS MODE
         *
         * GPS coordinates are required.
         */

        if (
            locationMode === "auto" &&
            (lat === "" || lng === "")
        ) {

            alert(
                "Waiting for GPS location. " +
                "Please allow location permission and try again."
            );

            return;
        }


        /*
         * MANUAL MODE
         *
         * Manual address is required.
         *
         * DO NOT require lat/lng here.
         * The Flask backend can geocode the address.
         */

        if (
            locationMode === "manual" &&
            manualAddress === ""
        ) {

            alert(
                "Please enter a complaint location."
            );

            if (manualAddressElement) {
                manualAddressElement.focus();
            }

            return;
        }


        // ==========================================
        // CHECK IMAGE
        // ==========================================

        const fileInput =
            document.getElementById("file");

        if (
            !fileInput ||
            !fileInput.files ||
            fileInput.files.length === 0
        ) {

            alert("Please select an image.");

            return;
        }


        // ==========================================
        // UI ELEMENTS
        // ==========================================

        const loading =
            document.getElementById("loading");

        const resultCard =
            document.getElementById("resultCard");


        // ==========================================
        // LOCK SUBMISSION
        // ==========================================

        predictionSubmitting = true;


        // Disable submit buttons
        const submitButtons =
            form.querySelectorAll(
                'button[type="submit"], input[type="submit"]'
            );

        submitButtons.forEach(function (button) {
            button.disabled = true;
        });


        // Show loading
        if (loading) {
            loading.style.display = "block";
        }


        // Hide old result
        if (resultCard) {
            resultCard.style.display = "none";
        }


        try {

            // ==========================================
            // CREATE FORM DATA
            // ==========================================

            const formData =
                new FormData(form);


            // Make sure location information is included
            formData.set(
                "location_mode",
                locationMode
            );

            if (manualAddress !== "") {

                formData.set(
                    "manual_address",
                    manualAddress
                );
            }

            if (lat !== "") {

                formData.set(
                    "lat",
                    lat
                );
            }

            if (lng !== "") {

                formData.set(
                    "lng",
                    lng
                );
            }


            console.log(
                "Sending ONE request to /predict..."
            );


            // ==========================================
            // SEND PREDICTION REQUEST
            // ==========================================

            const response =
                await fetch("/predict", {

                    method: "POST",

                    body: formData

                });


            console.log(
                "Prediction response:",
                response.status
            );


            // ==========================================
            // READ RESPONSE
            // ==========================================

            let data;

            try {

                data =
                    await response.json();

            }
            catch (jsonError) {

                throw new Error(
                    "Server returned an invalid response."
                );
            }


            // ==========================================
            // SERVER ERROR
            // ==========================================

            if (!response.ok || data.error) {

                const errorMessage =
                    data.error ||
                    "Unable to process the complaint.";

                if (resultCard) {

                    resultCard.style.display =
                        "block";

                    resultCard.innerHTML = `
                        <div class="alert alert-danger">
                            <h5>Server Error</h5>
                            <p>${errorMessage}</p>
                        </div>
                    `;
                }

                console.error(
                    "Prediction error:",
                    errorMessage
                );

                return;
            }


            // ==========================================
            // DISPLAY PREDICTION
            // ==========================================

            const issue =
                document.getElementById("issue");

            const confidence =
                document.getElementById("confidence");

            const department =
                document.getElementById("department");

            const authority =
                document.getElementById("authority");

            const location =
                document.getElementById("location");

            const description =
                document.getElementById("description");


            if (issue) {

                issue.innerText =
                    data.prediction || "";
            }


            if (confidence) {

                confidence.innerText =
                    (data.confidence || 0) + "%";
            }


            if (department) {

                department.innerText =
                    data.department || "";
            }


            if (authority) {

                authority.innerText =
                    data.authority || "";
            }


            if (location) {

                location.innerText =
                    data.location || "";
            }


            if (description) {

                description.innerText =
                    data.description || "";
            }


            // ==========================================
            // CONFIDENCE BAR
            // ==========================================

            const bar =
                document.getElementById(
                    "confidenceBar"
                );


            if (bar) {

                const confidenceValue =
                    Number(data.confidence) || 0;


                bar.style.width =
                    confidenceValue + "%";


                bar.innerText =
                    confidenceValue + "%";


                if (confidenceValue >= 90) {

                    bar.className =
                        "progress-bar bg-success";

                }
                else if (confidenceValue >= 70) {

                    bar.className =
                        "progress-bar bg-warning";

                }
                else {

                    bar.className =
                        "progress-bar bg-danger";
                }
            }


            // ==========================================
            // SHOW RESULT
            // ==========================================

            if (resultCard) {

                resultCard.style.display =
                    "block";


                resultCard.classList.add(
                    "fade-in"
                );


                resultCard.scrollIntoView({
                    behavior: "smooth"
                });
            }


            console.log(
                "Prediction completed successfully."
            );

        }


        catch (error) {

            console.error(
                "Prediction request failed:",
                error
            );


            if (resultCard) {

                resultCard.style.display =
                    "block";


                resultCard.innerHTML = `
                    <div class="alert alert-danger">
                        <h5>Server Error</h5>
                        <p>
                            ${error.message ||
                            "Unable to process the complaint. Please try again."}
                        </p>
                    </div>
                `;
            }

        }


        finally {

            // Hide loading
            if (loading) {
                loading.style.display = "none";
            }


            // Unlock submission
            predictionSubmitting = false;


            // Re-enable buttons
            submitButtons.forEach(function (button) {

                button.disabled = false;

            });

        }

    });

});