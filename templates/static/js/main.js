// Shared JavaScript for EcoCycle AI

document.addEventListener("DOMContentLoaded", () => {
    // Automatically hide temporary notifications.
    document.querySelectorAll(".flash-message").forEach((message) => {
        window.setTimeout(() => {
            message.style.transition = "opacity 0.4s ease";
            message.style.opacity = "0";

            window.setTimeout(() => message.remove(), 450);
        }, 5000);
    });

    // Prevent accidental double-submission of forms.
    document.querySelectorAll("form[data-loading]").forEach((form) => {
        form.addEventListener("submit", () => {
            const button = form.querySelector('button[type="submit"]');

            if (button) {
                button.disabled = true;
                button.textContent = "Please wait...";
            }
        });
    });
});