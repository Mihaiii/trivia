from fasthtml.common import *
from fasthtml.xtend import picolink
import asyncio
from collections import deque
from dataclasses import dataclass, field
import concurrent.futures
import json
import logging
import random
import threading
from typing import List
from auth import HuggingFaceClient

logging.basicConfig(level=logging.DEBUG)

QUESTION_COUNTDOWN_SEC = 5  # HOW MUCH TIME USERS HAVE TO ANSWER THE QUESTION? IN PROD WILL PROBABLY BE 18 or 20.
KEEP_FAILED_TOPIC_SEC = 5  # NUMBER OF SECONDS TO KEEP THE FAILED TOPIC IN THE UI (USER INTERFACE) BEFORE REMOVING IT FROM THE LIST
MAX_TOPIC_LENGTH_CHARS = 30  # DON'T ALLOW USER TO WRITE LONG TOPICS
MAX_NR_TOPICS_FOR_ALLOW_MORE = 6  # AUTOMATICALLY ADD TOPICS IF THE USERS DON'T BID/PROPOSE NEW ONES
NR_TOPICS_TO_BROADCAST = 5  # NUMBER OF TOPICS TO APPEAR IN THE UI. THE ACTUAL LIST CAN CONTAIN MORE THAN THIS.
BID_MIN_POINTS = 3  # MINIMUM NUMBER OF POINTS REQUIRED TO PLACE A TOPIC BID IN THE UI

db = database('uplayers.db')
players = db.t.players
if players not in db.t:
    players.create(id=int, name=str, points=int, pk='id')

current_topic = None

css = [
    picolink,
    Style('* { box-sizing: border-box; margin: 0; padding: 0; }'),
    Style('body { font-family: Arial, sans-serif; }'),
    Style('.container { display: flex; flex-direction: column; height: 100vh; }'),
    Style('.main { display: flex; flex: 1; flex-direction: row; }'),
    Style('.card { background-color: #f0f0f0; padding: 10px; margin-bottom: 10px; border: 1px solid #ccc; text-align: center; overflow: hidden;}'),
    Style('.item { display: inline-block; }'),
    Style('.left { float: left; }'),
    Style('.right { float: right }'),
    Style('.side-panel { display: flex; flex-direction: column; width: 20%; padding: 10px; border-right: 1px solid #ddd; flex: 1; transition: all 0.3s ease-in-out; flex-basis: 20%;}'),
    Style('.middle-panel { display: flex; flex-direction: column; flex: 1; padding: 10px; flex: 1; transition: all 0.3s ease-in-out; flex-basis: 60%;}'),
    Style('.login { margin-bottom: 10px; }'),
    # Style('@media (max-width: 768px) { .main { flex-direction: column; } .left-panel { width: 100%; border-right: none; border-bottom: 1px solid #ddd; } .right-panel { width: 100%; } }'),
    Style('.primary:active { background-color: #0056b3; }'),
    Style('@media (max-width: 768px) { .side-panel { display: none; } .middle-panel { display: block; flex: 1; } }'),
    Style('@media (min-width: 769px) { .login_wrapper { display: none; }')
]
#TODO: remove the app before making the repo public and properly handle the info, ofc
huggingface_client = HuggingFaceClient(
    client_id="f7542bbf-4343-482d-8b58-9343f4f9e3ca",
    client_secret="04f5de00-4158-44e2-a794-443f71586ee1",
    redirect_uri="http://localhost:8000/auth/callback"
)

@dataclass
class Question:
    title: str
    option_A: str
    option_B: str
    option_C: str
    option_D: str
    answer: str


@dataclass(order=True)
class Topic:
    points: int
    topic: str = field(compare=False)
    status: str = field(default="pending", compare=False)
    user: str = field(default="[bot]", compare=False)
    winners: List[str] = field(default_factory=list, compare=False)
    question: Question = field(default=None, compare=False)

    def __hash__(self):
        return hash((self.points, self.topic, self.user))

    def __eq__(self, other):
        if isinstance(other, Topic):
            return (self.points, self.topic, self.user) == (other.points, other.topic, other.user)
        return False


class TaskManager:
    def __init__(self, num_executors: int):
        self.topics = deque()
        self.topics_lock = asyncio.Lock()
        self.past_topics = deque(maxlen=5)
        self.past_topics_lock = asyncio.Lock()
        self.executors = [concurrent.futures.ThreadPoolExecutor(max_workers=1) for _ in range(num_executors)]
        self.executor_tasks = [set() for _ in range(num_executors)]
        self.current_topic_start_time = None
        self.current_timeout_task = None
        self.clients = {"unassigned_clients": set()}  # Track connected WebSocket clients
        self.clients_lock = threading.Lock()
        self.task = None
        self.countdown_var = QUESTION_COUNTDOWN_SEC
        self.current_topic = None

    def reset(self):
        self.countdown_var = QUESTION_COUNTDOWN_SEC

    async def run_executor(self, executor_id: int):
        while True:
            topic_to_process = None
            async with self.topics_lock:
                for topic in self.topics:
                    if all(topic not in tasks for tasks in self.executor_tasks):
                        if topic.status not in ["successful", "failed"]:
                            self.executor_tasks[executor_id].add(topic)
                            topic_to_process = topic
                            break

            if topic_to_process:
                await self.update_status(topic_to_process)
                async with self.topics_lock:
                    self.executor_tasks[executor_id].remove(topic_to_process)
            await asyncio.sleep(0.1)  # Avoid busy-waiting

    async def update_status(self, topic: Topic):
        await asyncio.sleep(1)  # Simulate processing time
        should_consume = False
        async with self.topics_lock:
            # HERE WE SIMULATE THE LLM CALLS AND STATUS RESPONSES. FOR THE MOMENT, WE FAKE THE PROCESS AND MOVE EVERYTHING IN SUCCESSFUL STATUS.
            if topic.status == "pending":
                topic.status = random.choice(["computing"])  # TODO: ["computing", "failed"]
            elif topic.status == "computing":
                # SIMULATE A LLM GENERATED QUESTION WITH OPTIONS AND A CORRECT ANSWER
                topic.question = Question(f"Question title for topic: {topic.topic}",
                                          f"option A for {topic.topic}",
                                          f"option B for {topic.topic}",
                                          f"option C for {topic.topic}",
                                          f"option D for {topic.topic}",
                                          "C")
                topic.status = random.choice(["successful"])  # TODO: ["successful", "failed"]

            await self.broadcast_next_topics()

            if topic.status == "successful" and self.current_topic is None:
                should_consume = True
            if topic.status == "failed":
                await asyncio.create_task(self.remove_failed_topic(topic))
            # logging.debug(f"Topic updated: {topic.topic} to {topic.status}")
        if should_consume:
            if self.task:
                self.task.cancel()
            self.reset()
            self.task = asyncio.create_task(self.count())
            await self.consume_successful_topic()

    async def consume_successful_topic(self):
        topic = None
        logging.debug(f"consume_successful_topic before lock")
        async with self.topics_lock:
            logging.debug(f"consume_successful_topic after lock")
            successful_topics = [t for t in self.topics if t.status == "successful"]
            # logging.debug(successful_topics)
            if successful_topics:
                topic = successful_topics[0]  # Get the highest points successful topic
                logging.debug(f"Topic obtained: {topic.topic}")
                self.topics.remove(topic)
                self.current_topic = topic
                self.current_topic_start_time = asyncio.get_event_loop().time()
                self.current_timeout_task = asyncio.create_task(self.topic_timeout())
                
        if topic:
            logging.debug(f"We have a topic to broadcast: {topic.topic}")
            await self.broadcast_current_question()
            await self.broadcast_next_topics()
            await self.broadcast_past_topics()
            logging.debug(f"Topic consumed: {topic.topic}")
            logging.debug(f"Length of self.topics: {len(self.topics)}")
        return topic

    async def topic_timeout(self):
        try:
            await asyncio.sleep(QUESTION_COUNTDOWN_SEC)
            logging.debug(f"{QUESTION_COUNTDOWN_SEC} seconds timeout completed")
            await self.check_topic_completion()  # Check if the topic should be completed
        except asyncio.CancelledError:
            logging.debug("Timeout task cancelled")
            pass  # Handle cancellation if the task is cancelled

    async def check_topic_completion(self):
        should_consume = False
        logging.debug("check_topic_completion before self.topics_lock")
        async with self.topics_lock:
            logging.debug("check_topic_completion after self.topics_lock")
            current_time = asyncio.get_event_loop().time()
            logging.debug(current_time)
            logging.debug(self.current_topic_start_time)
            if self.current_topic and (current_time - self.current_topic_start_time >= QUESTION_COUNTDOWN_SEC - 0.4):
                logging.debug(f"Completing topic: {self.current_topic.topic}")
                should_consume = True
        if should_consume:
            if self.task:
                self.task.cancel()
                self.reset()
            self.task = asyncio.create_task(self.count())
            async with self.past_topics_lock:
                self.past_topics.append(self.current_topic)
            await self.consume_successful_topic()

    async def remove_failed_topic(self, topic: Topic):
        await asyncio.sleep(KEEP_FAILED_TOPIC_SEC)
        async with self.topics_lock:
            if topic in self.topics and topic.status == "failed":
                self.topics.remove(topic)
                await self.broadcast_next_topics()
        logging.debug(f"Failed topic removed: {topic.topic}")

    async def monitor_topics(self):
        while True:
            need_default_topics = False
            async with self.topics_lock:
                if all(topic.status in ["successful", "failed"] for topic in self.topics):
                    need_default_topics = True

            if need_default_topics:
                await self.add_default_topics()
            await asyncio.sleep(1)  # Check periodically

    async def add_default_topics(self):
        async with self.topics_lock:
            if len(self.topics) < MAX_NR_TOPICS_FOR_ALLOW_MORE:
                for i in range(6):
                    self.topics.append(Topic(0, f"Default Topic {i}", user="[bot]"))
                self.topics = deque(sorted(self.topics, reverse=True))
                await self.broadcast_next_topics()
                logging.debug("Default topics added")

    async def add_user_topic(self, points: int = 100, topic: str = "example"):
        async with self.topics_lock:
            self.topics.append(Topic(points=points, topic=topic, user="user"))
            self.topics = deque(sorted(self.topics, reverse=True))
            await self.broadcast_next_topics()
            logging.debug("User topic added")

    async def broadcast_next_topics(self, client=None):
        next_topics = list(self.topics)[:NR_TOPICS_TO_BROADCAST]
        status_dict = {
            'failed': 'red',
            'pending': 'white',
            'computing': 'yellow',
            'successful': 'green'
        }
        next_topics_html = [Div(Div(f"{item.topic if item.status not in ['pending', 'failed'] else 'Topic Censored'}"),
                                Div(item.user, cls="item left"), Div(f"{item.points} pts", cls="item right"),
                                cls="card", style=f"background-color: {status_dict[item.status]}") for item in
                            next_topics]
        
        await self.send_to_clients(Div(*next_topics_html, id="next_topics"), client)

    async def send_to_clients(self, element, client=None):
        with self.clients_lock:
            clients = (self.clients if client is None else {'dd': [client]}).copy()
        for client in [item for subset in clients.values() for item in subset]:
            try:
                await client(element)
            except:
                for key, client_set in self.clients.items():
                    if client in client_set:
                        client_set.remove(client)
                        logging.debug(f"Removed disconnected client: {client}")
                        break
                
    async def broadcast_past_topics(self, client=None):
        if len(list(self.past_topics)) > 0:
            async with self.past_topics_lock:
                past_topic = list(self.past_topics)[-1]
            random_numbers = random.sample(range(1, 11), 10)
            past_topic.winners = [f"user{num}" for num in random_numbers]
            past_topic.question.title = "example question?"
            past_topic.question.answer = "example answer"

            past_topics_html = Div(Div(f"{past_topic.topic} - {past_topic.user}", style="text-align: center;"),
                                   Div(f"Q: {past_topic.question.title}"),
                                   Div(f"A: {past_topic.question.answer}"),
                                   Div(f"Winners: ", Ol(Li(f"{winner} - {(len(past_topic.winners) - past_topic.winners.index(winner)) * 10}pts") for winner in past_topic.winners)),
                                   cls="card")
            await self.send_to_clients(Div(past_topics_html, id="past_topics"), client)

    async def broadcast_current_question(self, client=None):
        current_question_info = Div(
            Div(
                Div(self.current_topic.question.title, style="font-size: 30px;"),
                Div(self.current_topic.user, cls="item left"),
                Div(f"{self.current_topic.points} pts", cls="item right"),
                cls="card"),
            unselectedOptions()
        )
        await self.send_to_clients(Div(current_question_info, id="current_question_info"), client)

    async def count(self):
        self.countdown_var = QUESTION_COUNTDOWN_SEC
        # await self.consume_successful_topic()
        while self.countdown_var >= 0:
            await self.broadcast_countdown()
            await asyncio.sleep(1)
            self.countdown_var -= 1

    async def broadcast_countdown(self, client=None):
        countdown_format = self.countdown_var if self.countdown_var >= 10 else f"0{self.countdown_var}"
        countdown_div = Div(f"{countdown_format}s", cls="countdown", style="text-align: center; font-size: 40px;", id="countdown")
        await self.send_to_clients(countdown_div, client)


async def app_startup():
    num_executors = 2  # Change this to run more executors
    task_manager = TaskManager(num_executors)
    app.state.task_manager = task_manager
    asyncio.create_task(task_manager.monitor_topics())
    for i in range(num_executors):
        asyncio.create_task(task_manager.run_executor(i))


app = FastHTML(hdrs=(css), ws_hdr=True, on_startup=[app_startup], debug=True)
rt = app.route
setup_toasts(app)

@rt('/choose_option_A')
async def post(session, app):
    if('session_id' not in session):
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button.", "error")
        return unselectedOptions()
    
    task_manager = app.state.task_manager
    await task_manager.check_topic_completion()
    div_a = Div(
        Button(task_manager.current_topic.question.option_A, cls="primarly", hx_post="/choose_option_A",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_B, cls="secondary", hx_post="/choose_option_B",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_C, cls="secondary", hx_post="/choose_option_C",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_D, cls="secondary", hx_post="/choose_option_D",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        cls="options",
        style="display: flex; flex-direction: column; gap: 10px; ",
        id="question_options"
    )
    
    for client in task_manager.clients[session['session_id']]:
        await task_manager.send_to_clients(div_a, client)


@rt('/choose_option_B')
async def post(session):
    if('session_id' not in session):
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button.", "error")
        return unselectedOptions()
    
    task_manager = app.state.task_manager
    await task_manager.check_topic_completion()
    div_b = Div(
        Button(task_manager.current_topic.question.option_A, cls="secondary", hx_post="/choose_option_A",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_B, cls="primarly", hx_post="/choose_option_B",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_C, cls="secondary", hx_post="/choose_option_C",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_D, cls="secondary", hx_post="/choose_option_D",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        cls="options",
        style="display: flex; flex-direction: column; gap: 10px; ",
        id="question_options"
    )
    
    for client in task_manager.clients[session['session_id']]:
        await task_manager.send_to_clients(div_b, client)


@rt('/choose_option_C')
async def post(session, app):
    if('session_id' not in session):
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button.", "error")
        return unselectedOptions()
    
    task_manager = app.state.task_manager
    await task_manager.check_topic_completion()
    div_c =  Div(
        Button(task_manager.current_topic.question.option_A, cls="secondary", hx_post="/choose_option_A",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_B, cls="secondary", hx_post="/choose_option_B",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_C, cls="primarly", hx_post="/choose_option_C",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_D, cls="secondary", hx_post="/choose_option_D",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        cls="options",
        style="display: flex; flex-direction: column; gap: 10px; ",
        id="question_options"
    )
    
    for client in task_manager.clients[session['session_id']]:
        await task_manager.send_to_clients(div_c, client)


@rt('/choose_option_D')
async def post(session):
    if('session_id' not in session):
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button.", "error")
        return unselectedOptions()
    
    task_manager = app.state.task_manager
    await task_manager.check_topic_completion()
    
    div_d = Div(
        Button(task_manager.current_topic.question.option_A, cls="secondary", hx_post="/choose_option_A",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_B, cls="secondary", hx_post="/choose_option_B",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_C, cls="secondary", hx_post="/choose_option_C",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(task_manager.current_topic.question.option_D, cls="primarly", hx_post="/choose_option_D",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        cls="options",
        style="display: flex; flex-direction: column; gap: 10px; ",
        id="question_options"
    )
    
    for client in task_manager.clients[session['session_id']]:
        await task_manager.send_to_clients(div_d, client)

def unselectedOptions():
    task_manager = app.state.task_manager
    return Div(
        Button(task_manager.current_topic.question.option_A, cls="primary", hx_post="/choose_option_A",
                hx_target="#question_options", hx_swap="outerHTML"),
        Button(task_manager.current_topic.question.option_B, cls="primary", hx_post="/choose_option_B",
                hx_target="#question_options", hx_swap="outerHTML"),
        Button(task_manager.current_topic.question.option_C, cls="primary", hx_post="/choose_option_C",
                hx_target="#question_options", hx_swap="outerHTML"),
        Button(task_manager.current_topic.question.option_D, cls="primary", hx_post="/choose_option_D",
                hx_target="#question_options", hx_swap="outerHTML"),
        cls="options",
        style="display: flex; flex-direction: column; gap: 10px; ",
        id="question_options"
    )

def bid_form():
    return Div(Form(Input(type='text', name='topic', placeholder="TOPIC"),
                 Input(type="number", placeholder="NR POINTS", min=BID_MIN_POINTS, name='points'),
                 Button('BID', cls='primary', style="width: 100%;"),
                 action='/', hx_post='/bid'), hx_swap="outerHTML", style="border: 5px solid black; padding: 10px;"
            )

@rt("/auth/callback")
def get(app, session, code: str = None):
    try:
        user_info = huggingface_client.retr_info(code)
    except Exception as e:
        error_message = str(e)
        print(f"Error occurred: {error_message}")
        return f"An error occurred: {error_message}"
    user_id = user_info.get("preferred_username")    
    if 'session_id' not in session:
        session['session_id'] = user_id

    logging.info(f"Client connected: {user_id}")
    return RedirectResponse(url="/")

tabs = Nav(
    A("PLAY", href="/", role="button", cls="secondary"),
    A("LEADERBOARD", href="/leaderboard", role="button", cls="secondary"),
    A("FAQ", href="/faq", role="button", cls="secondary"),
    cls="tabs"
)
    
@rt('/')
async def get(session, app, request):
    task_manager = app.state.task_manager
    user_id = None
    if 'session_id' in session:
        user_id = session['session_id']
        if user_id not in task_manager.clients:
            task_manager.clients[user_id] = set()
        
        db_player = db.q(f"select * from {players} where {players.c.name} like '{user_id}' limit 1")

        if not db_player:
            current_points = 20
            players.insert({'name': user_id, 'points': current_points})
        else:
            current_points = db_player[0]['points']

    current_question_info = Div(id="current_question_info")
    left_panel = Div(
        Div(id="next_topics"),
        bid_form()
        , cls='side-panel'
    )
    if user_id:
        top_right_corner = Div(user_id + ": " + str(current_points) + " pct", cls='login', style="max-width: fit-content; margin-left: auto; margin-right: auto;")
    else:
        top_right_corner = Div(A(Img(src="https://huggingface.co/datasets/huggingface/badges/resolve/main/sign-in-with-huggingface-xl.svg"), href=huggingface_client.login_link_with_state()), cls='login', style="max-width: fit-content; margin-left: auto; margin-right: auto;")

    middle_panel = Div(
        Div(top_right_corner, cls='login_wrapper'),
        Div(id="countdown"),
        current_question_info,
        cls="middle-panel"
    )
    right_panel = Div(
        top_right_corner,
        Div(id="past_topics"),
        cls="side-panel"
    )
    main_content = Div(
        left_panel,
        middle_panel,
        right_panel,
        cls="main"
    )
    container = Div(
        tabs,
        main_content,
        cls="container",
        hx_ext='ws', ws_connect='/ws'
    )
    return container

@rt('/leaderboard')
async def get():
    db_player = db.q(f"select * from {players} order by points desc limit 20")
    cells = [Tr(Td(row['name']), Td(row['points'])) for row in db_player]
    main_content = Table(Tr(Th(B('Huggingface Username')), Th(B("Points"))), *cells)
    return Div(
        tabs,
        main_content,
        cls="container"
    )

@rt('/faq')
async def get():
    return Div(
        tabs,
        Div("not yet implemented"),
        cls="container"
    )

@rt("/bid")
async def post(session, topic: str, points: int):
    if('session_id' not in session):
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button.", "error")
        return bid_form()
    print(f"Topic: {topic}, points: {points}")
    #TODO: subtract the points of the user and do the check it can bid (has end result >=0 points)
    task_manager = app.state.task_manager
    await task_manager.add_user_topic(topic=topic, points=points)
    return bid_form()


async def on_connect(send, ws):
    client_key = "unassigned_clients"
    if ws.scope['session'] and ws.scope['session']['session_id']:
        client_key = ws.scope['session']['session_id']
    task_manager = app.state.task_manager
    with task_manager.clients_lock:
        if not task_manager.clients[client_key]:
            task_manager.clients[client_key] = set()
        task_manager.clients[client_key].add(send)
    await task_manager.broadcast_next_topics(send)
    if task_manager.current_topic:
        await task_manager.broadcast_current_question(send)
    await task_manager.broadcast_past_topics(send)


async def on_disconnect(send, session):
    print("Calling on_disconnect")
    print(len(app.state.task_manager.clients))
    task_manager = app.state.task_manager
    with task_manager.clients_lock:
        print("I'm inside the lock")
        if send in task_manager.clients.copy():
            for key, client_set in task_manager.clients.items():
                if send in client_set:
                    client_set.remove(send)
                    break
            if session:
                session['session_id'] = None
            print("Client was removed and printing len clients")
            print(len(task_manager.clients))


@app.ws('/ws', conn=on_connect, disconn=on_disconnect)
async def ws(send):
    pass


run_uv()