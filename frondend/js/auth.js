// TEMP admin credentials (later move to Flask)
const ADMIN_USER = "admin";
const ADMIN_PASS = "admin123";

function login() {
  const user = document.getElementById("username").value;
  const pass = document.getElementById("password").value;
  const msg = document.getElementById("login-msg");

  if (user === ADMIN_USER && pass === ADMIN_PASS) {
    msg.style.color = "green";
    msg.textContent = "Login successful!";
    setTimeout(() => {
      window.location.href = "dashboard.html";
    }, 800);
  } else {
    msg.style.color = "red";
    msg.textContent = "Invalid credentials";
  }
}

function showCreate() {
  alert("Create account will be enabled after backend integration");
}
