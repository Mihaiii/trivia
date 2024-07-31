from fasthtml.oauth import _AppClient, WebApplicationClient, GoogleAppClient
import secrets
from fastcore.basics import patch
import os

class HuggingFaceClient(_AppClient):
    "A `WebApplicationClient` for HuggingFace oauth2"

    base_url = "https://huggingface.co/oauth/authorize"
    token_url = "https://huggingface.co/oauth/token"
    info_url = "https://huggingface.co/oauth/userinfo"
    id_key = 'sub'

    def __init__(self, client_id, client_secret, redirect_uri=None, redirect_uris=None, code=None, scope=None, state=None, **kwargs):
        if redirect_uris and not redirect_uri: redirect_uri = redirect_uris[0]
        if not scope: scope=["openid","profile"]
        if not state: state=secrets.token_urlsafe(16)
        super().__init__(client_id, client_secret, redirect_uri, code=code, scope=scope, state=state, **kwargs)

@patch
def login_link_with_state(self:WebApplicationClient, scope=None, state=None):
    "Get a login link for this client"
    if not scope: scope=self.scope
    if not state: state=self.state
    return self.prepare_request_uri(self.base_url, self.redirect_uri, scope, state)


google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
google_redirect_uri = "https://mihaiii-trivia.hf.space/google/auth/callback"

GoogleClient = GoogleAppClient(client_id=google_client_id, redirect_uri=google_redirect_uri,
                               client_secret=google_client_secret)
