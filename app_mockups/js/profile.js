function navigateTo(page) { window.location.href = page; }
function toggleNotifications(el) {
  const toggle = el.querySelector('.toggle-switch');
  toggle.classList.toggle('active');
}
