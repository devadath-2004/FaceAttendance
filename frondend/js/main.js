// Navigation helpers
function goTo(page) {
  window.location.href = page;
}

// Home page buttons
document.addEventListener("DOMContentLoaded", () => {
  const startBtn = document.querySelector(".btn-primary");
  const registerBtn = document.querySelector(".btn-outline");

  if (startBtn) {
    startBtn.onclick = () => goTo("login.html");
  }

  if (registerBtn) {
    registerBtn.onclick = () => goTo("register.html");
  }

  // Navbar buttons
  document.querySelectorAll("[data-nav]").forEach(btn => {
    btn.onclick = () => goTo(btn.dataset.nav);
  });
});
