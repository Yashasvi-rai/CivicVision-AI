/* =========================================================
   CIVIC VISION AI - THEME + UI
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {

    const html = document.documentElement;
    const themeButton = document.getElementById("themeToggle");

    // Load saved theme
    const savedTheme = localStorage.getItem("civicVisionTheme");

    if (savedTheme) {
        html.setAttribute("data-theme", savedTheme);
    } else {
        html.setAttribute("data-theme", "light");
    }

    updateThemeIcon();

    // Theme toggle
    if (themeButton) {
        themeButton.addEventListener("click", function () {

            const currentTheme =
                html.getAttribute("data-theme") || "light";

            const newTheme =
                currentTheme === "dark" ? "light" : "dark";

            html.setAttribute("data-theme", newTheme);

            localStorage.setItem(
                "civicVisionTheme",
                newTheme
            );

            updateThemeIcon();
        });
    }

    function updateThemeIcon() {

        if (!themeButton) return;

        const currentTheme =
            html.getAttribute("data-theme");

        themeButton.innerHTML =
            currentTheme === "dark"
                ? "☀️"
                : "🌙";

        themeButton.title =
            currentTheme === "dark"
                ? "Switch to light mode"
                : "Switch to dark mode";
    }

    // Password show/hide
    document.querySelectorAll(".password-toggle").forEach(button => {

        button.addEventListener("click", function () {

            const input =
                document.getElementById(
                    this.dataset.target
                );

            if (!input) return;

            if (input.type === "password") {

                input.type = "text";
                this.innerHTML = "🙈";

            } else {

                input.type = "password";
                this.innerHTML = "👁️";
            }
        });
    });

});