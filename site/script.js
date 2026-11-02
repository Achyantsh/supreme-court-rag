(function () {
  const root = document.documentElement;
  const toggle = document.querySelector('.theme-toggle');
  const stored = localStorage.getItem('scrag-theme');
  if (stored === 'light') root.classList.add('light');
  function updateToggle() {
    const light = root.classList.contains('light');
    toggle.setAttribute('aria-pressed', String(light));
    toggle.setAttribute('aria-label', light ? 'Switch to dark theme' : 'Switch to light theme');
    toggle.querySelector('.theme-label').textContent = light ? 'Dark mode' : 'Light mode';
  }
  updateToggle();
  toggle.addEventListener('click', function () {
    root.classList.toggle('light');
    localStorage.setItem('scrag-theme', root.classList.contains('light') ? 'light' : 'dark');
    updateToggle();
  });
}());
