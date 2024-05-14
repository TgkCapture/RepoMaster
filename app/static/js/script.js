// smooth scrolling functionality
document.querySelectorAll('nav a').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
      const targetId = this.getAttribute('href').substring(1);
  
      if (targetId.startsWith('#')) { // Internal link (smooth scroll)
        e.preventDefault();
        const targetSection = document.getElementById(targetId);
        window.scrollTo({
          top: targetSection.offsetTop,
          behavior: 'smooth'
        });
      } else { 
      }
    });
  });
  

function signInWithGitHub() {
    // Opens a GitHub OAuth login popup window
    
    var width = 600;
    var height = 600;
    var left = (window.innerWidth - width) / 2;
    var top = (window.innerHeight - height) / 2;
    var url = 'https://github.com/login/oauth/authorize?client_id=your_client_id&scope=user:email';
    var options = 'toolbar=no, location=no, directories=no, status=no, menubar=no, scrollbars=no, resizable=no, copyhistory=no, width=' + width + ', height=' + height + ', top=' + top + ', left=' + left;
    window.open(url, 'GitHub Sign-in', options);
}

document.getElementById('github-login').addEventListener('click', function(event) {
    event.preventDefault();
    signInWithGitHub();
});

$('[data-github]').each(function () {
  var _this = this;
  var repo = $(_this).data('github')

  fetch('https://api.github.com/repos/' + repo).then(function (response) {
      return response.json();
  }).then(function (response) {
      $(_this).find('[data-forks]').text(response.forks);
      $(_this).find('[data-stars]').text(response.stargazers_count);
  });
  });