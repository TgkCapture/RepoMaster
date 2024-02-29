from authlib.integrations.flask_client import OAuth

oauth = OAuth()

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
)
