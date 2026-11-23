// Smooth scrolling for in-page navigation links (e.g. href="#services")
document.querySelectorAll('nav a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    const targetId = this.getAttribute('href').substring(1);
    const targetSection = targetId && document.getElementById(targetId);

    if (targetSection) {
      e.preventDefault();
      window.scrollTo({
        top: targetSection.offsetTop,
        behavior: 'smooth'
      });
    }
  });
});
