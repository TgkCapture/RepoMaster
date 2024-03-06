from authlib.integrations.flask_client import OAuth
from flask_dance.contrib.github import make_github_blueprint

oauth = OAuth()

# GitHub OAuth configuration
github_bp = make_github_blueprint(
    client_id='your_client_id',
    client_secret='your_client_secret',
    scope='user:email repo'
)

# Register GitHub blueprint with OAuth
oauth.register(
    name='github',
    client_id='your_client_id',
    client_secret='your_client_secret',
    authorize_url='https://github.com/login/oauth/authorize',
    authorize_params=None,
    access_token_url='https://github.com/login/oauth/access_token',
    access_token_params=None,
    refresh_token_url=None,
    refresh_token_params=None,
    redirect_uri=None,
    client_kwargs={'scope': 'user:email repo'},
    server_metadata_url=None,
    blueprint=github_bp
)
