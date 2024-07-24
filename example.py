import asyncio
from fasthtml.common import *
import threading
from fasthtml.oauth import _AppClient, WebApplicationClient
import secrets
from fastcore.basics import patch
### Oauth client

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

###

# #TODO: Please make an oauth app here: https://huggingface.co/docs/hub/en/oauth
# It doesn't take more than 1 minute
# Make sure you add http://localhost:8000/auth/callback at Redirect URLs
huggingface_client = HuggingFaceClient(
    client_id="f7542bbf-4343-482d-8b58-9343f4f9e3ca",
    client_secret="04f5de00-4158-44e2-a794-443f71586ee1",
    redirect_uri="http://localhost:8000/auth/callback"
)


not_logged_in_clients = set()
logged_in_clients = set()
clients_lock = threading.Lock()

class Counter:
    def __init__(self, start_nr):
        self.nr = start_nr
        
    async def count(self):
        while True:
            await self.broadcast()
            await asyncio.sleep(1)
            self.nr += 1
        
    async def broadcast(self):
        with clients_lock:
            for client in logged_in_clients.copy():
                try:
                    await client(Div(f"{self.nr}", style="text-align: center; color: red; font-size: 40px", id="some_nr"))
                except:
                    logged_in_clients.remove(client)
                    
            for client in not_logged_in_clients.copy():
                try:
                    await client(Div(f"{self.nr}", style="text-align: center; color: green; font-size: 40px", id="some_nr"))
                except:
                    if client in not_logged_in_clients:
                        not_logged_in_clients.remove(client)

async def on_connect(session, request, send):
    #print("on_connect")
    #print(request.cookies)
    if session:
        await send(Div("We have a session object on on_connect", id="session_text"))
    else:
        await send(Div("We don't have a session object on on_connect", id="session_text"))
        
    with clients_lock:
        not_logged_in_clients.add(send)


async def on_disconnect(send):
    with clients_lock:
        if send in not_logged_in_clients:
            not_logged_in_clients.remove(send)
        if send in logged_in_clients:
            logged_in_clients.remove(send)             

async def app_startup():
    counter = Counter(0)
    asyncio.create_task(counter.count())
    
app = FastHTML(ws_hdr=True, on_startup=[app_startup], debug=True)
rt = app.route

@app.ws('/ws', conn=on_connect, disconn=on_disconnect)
async def ws(send, request):
    print("ws")
    print(request.cookies)
    pass

@rt("/auth/callback")
def get(code: str = None):
    user_info = huggingface_client.retr_info(code)
    
    #TODO: transfer from not_logged_in_clients to logged_in_clients
    #client = "??"
    #not_logged_in_clients.remove(client)
    #logged_in_clients.add(client)
    
    return RedirectResponse(url="/")

@rt('/')
async def get(request, session):
    print(len(request.cookies))
    print(request.cookies['session_'])
    print(session)
    return Div(
        Div(id="session_text"),
        Div(id="some_nr"),
        A(Img(src="https://huggingface.co/datasets/huggingface/badges/resolve/main/sign-in-with-huggingface-xl.svg"), href=huggingface_client.login_link_with_state()),
        hx_ext='ws',
        ws_connect='/ws'
    )
    
run_uv()