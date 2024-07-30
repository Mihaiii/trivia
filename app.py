from fasthtml.common import *
from fasthtml.xtend import picolink
import asyncio
from collections import deque
from dataclasses import dataclass, field
import concurrent.futures
import logging
import random
import threading
from typing import List, Tuple
from auth import HuggingFaceClient
from difflib import SequenceMatcher
from scripts import ThemeSwitch

logging.basicConfig(level=logging.DEBUG)

QUESTION_COUNTDOWN_SEC = 50  # HOW MUCH TIME USERS HAVE TO ANSWER THE QUESTION? IN PROD WILL PROBABLY BE 18 or 20.
KEEP_FAILED_TOPIC_SEC = 5  # NUMBER OF SECONDS TO KEEP THE FAILED TOPIC IN THE UI (USER INTERFACE) BEFORE REMOVING IT FROM THE LIST
MAX_TOPIC_LENGTH_CHARS = 30  # DON'T ALLOW USER TO WRITE LONG TOPICS
MAX_NR_TOPICS_FOR_ALLOW_MORE = 6  # AUTOMATICALLY ADD TOPICS IF THE USERS DON'T BID/PROPOSE NEW ONES
NR_TOPICS_TO_BROADCAST = 5  # NUMBER OF TOPICS TO APPEAR IN THE UI. THE ACTUAL LIST CAN CONTAIN MORE THAN THIS.
BID_MIN_POINTS = 3  # MINIMUM NUMBER OF POINTS REQUIRED TO PLACE A TOPIC BID IN THE UI
TOPIC_MAX_LENGTH = 25 # MAX LENGTH OF THE USER PROVIDED TOPIC (WE REDUCE MALICIOUS INPUT)
MAX_NR_TOPICS = 50
DUPLICATE_TOPIC_THRESHOLD = 0.9

db = database('uplayers.db')
players = db.t.players
if players not in db.t:
    players.create(id=int, name=str, points=int, pk='id')


def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


css = [
    picolink,
    Style('* { box-sizing: border-box; margin: 0; padding: 0; }'),
    Style('body { font-family: Arial, sans-serif; }'),
    Style('.container { display: flex; flex-direction: column; height: 100vh; }'),
    Style('.main { display: flex; flex: 1; flex-direction: row; }'),
    Style('.card { padding: 10px; margin-bottom: 10px; border: 1px solid #ccc; text-align: center; overflow: hidden;}'),
    Style('.past-card { padding: 10px; margin-bottom: 10px; border: 1px solid #ccc; text-align: left; overflow: hidden;}'),
    Style('.item { display: inline-block; }'),
    Style('.left { float: left; }'),
    Style('.right { float: right }'),
    Style('.side-panel { display: flex; flex-direction: column; width: 20%; padding: 10px; flex: 1; transition: all 0.3s ease-in-out; flex-basis: 20%;}'),
    Style('.middle-panel { display: flex; flex-direction: column; flex: 1; padding: 10px; flex: 1; transition: all 0.3s ease-in-out; flex-basis: 60%;}'),
    Style('.login { margin-bottom: 10px; max-width: fit-content; margin-left: auto; margin-right: auto;}'),
    Style('.primary:active { background-color: #0056b3; }'),
    Style('.last-tab  { display: flex; align-items: center;  justify-content: center;}'),
    Style('@media (max-width: 768px) { .side-panel { display: none; } .middle-panel { display: block; flex: 1; } }'),
    Style('@media (min-width: 769px) { .login_wrapper { display: none; } .bid_wrapper {display: none; }')
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
    correct_answer: str


@dataclass(order=True)
class Topic:
    points: int
    topic: str = field(compare=False)
    status: str = field(default="pending", compare=False)
    user: str = field(default="[bot]", compare=False)
    answers: List[Tuple[str, str]] = field(default_factory=list, compare=False)
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
        self.answers_lock = asyncio.Lock()
        self.past_topic = None
        self.executors = [concurrent.futures.ThreadPoolExecutor(max_workers=1) for _ in range(num_executors)]
        self.executor_tasks = [set() for _ in range(num_executors)]
        self.current_topic_start_time = None
        self.current_timeout_task = None
        self.clients = {"unassigned_clients": set()}  # Track connected WebSocket clients
        self.clients_lock = threading.Lock()
        self.task = None
        self.countdown_var = QUESTION_COUNTDOWN_SEC
        self.current_topic = None
        self.user_dict = {}

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
            await self.compute_winners()
            await self.broadcast_past_topic()
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
            self.past_topic = self.current_topic
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
            if len(self.topics) > MAX_NR_TOPICS:
                self.topics = self.topics[::-MAX_NR_TOPICS]
            await self.broadcast_next_topics()
            logging.debug("User topic added")

    async def broadcast_next_topics(self, client=None):
        next_topics = list(self.topics)[:NR_TOPICS_TO_BROADCAST]
        status_dict = {
            'failed': '#dc552c',
            'pending': '#ede7dd',
            'computing': '#cfb767',
            'successful': '#77ab59'
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
                with self.clients_lock:
                    key_to_remove = None
                    for key, client_set in self.clients.items():
                        if client in client_set:
                            client_set.remove(client)
                            if len(client_set) == 0:
                                key_to_remove = key
                            logging.debug(f"Removed disconnected client: {client}")
                            break
                    if key_to_remove:
                        self.clients.pop(key_to_remove)
                        
    async def compute_winners(self):
        if self.past_topic:
            async with self.answers_lock:
                self.past_topic.winners = [a[0] for a in self.past_topic.answers if a[1] == self.past_topic.question.correct_answer]
            
            ids = ", ".join([str(self.user_dict[w]) for w in self.past_topic.winners])
            db_player = db.q(f"select * from {players} where {players.c.id} in ({ids})")
            
            for db_winner in db_player:
                winner_name = db_winner['name']
                db_winner['points'] += (len(self.past_topic.winners) - self.past_topic.winners.index(winner_name)) * 10
                players.update(db_winner)
                
                elem = Div(winner_name + ": " + str(db_player[0]['points']) + " pts", cls='login', id='login_points')
                for client in self.clients[winner_name]:
                    await self.send_to_clients(elem, client)
                            
    async def broadcast_past_topic(self, client=None):
        if self.past_topic:                
            ans = getattr(self.past_topic.question, f"option_{self.past_topic.question.correct_answer}")
            past_topic_html = Div(Div(B("Question:"), P(self.past_topic.question.title)),
                                   Div(B("Correct answer:"), P(ans)),
                                   Div(
                                        B("Winners:"),
                                        Table(*[Tr(Td(winner), Td(f"{(len(self.past_topic.winners) - self.past_topic.winners.index(winner)) * 10} pts")) for winner in self.past_topic.winners]),
                                   ),
                                   cls="past-card")

            await self.send_to_clients(Div(past_topic_html, id="past_topic"), client)

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
        while self.countdown_var >= 0:
            await self.broadcast_countdown()
            await asyncio.sleep(1)
            self.countdown_var -= 1

    async def broadcast_countdown(self, client=None):
        countdown_format = self.countdown_var if self.countdown_var >= 10 else f"0{self.countdown_var}"
        style = "color: red;" if self.countdown_var <= 5 else ""
        countdown_div = Div(f"{countdown_format}", cls="countdown", style="text-align: center; font-size: 40px;" + style, id="countdown")
        await self.send_to_clients(countdown_div, client)


async def app_startup():
    num_executors = 2  # Change this to run more executors
    task_manager = TaskManager(num_executors)
    app.state.task_manager = task_manager
    results = db.q(f"SELECT {players.c.name}, {players.c.id} FROM {players}")
    task_manager.user_dict = {row['name']: row['id'] for row in results}
    asyncio.create_task(task_manager.monitor_topics())
    for i in range(num_executors):
        asyncio.create_task(task_manager.run_executor(i))


app = FastHTML(hdrs=(css, ThemeSwitch()), ws_hdr=True, on_startup=[app_startup], debug=True)
rt = app.route
setup_toasts(app)

@rt('/choose_option_A')
async def post(session, app):
    if('session_id' not in session):
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button to sign in with Huggingface.", "error")
        return unselectedOptions()
    
    task_manager = app.state.task_manager
    
    async with task_manager.answers_lock:
        task_manager.current_topic.answers = [a for a in task_manager.current_topic.answers if a[0] != session['session_id']]
        task_manager.current_topic.answers.append((session['session_id'], "A"))
        
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
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button to sign in with Huggingface.", "error")
        return unselectedOptions()
    
    task_manager = app.state.task_manager
    
    async with task_manager.answers_lock:
        task_manager.current_topic.answers = [a for a in task_manager.current_topic.answers if a[0] != session['session_id']]
        task_manager.current_topic.answers.append((session['session_id'], "B"))
    
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
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button to sign in with Huggingface.", "error")
        return unselectedOptions()
    
    task_manager = app.state.task_manager
    
    async with task_manager.answers_lock:
        task_manager.current_topic.answers = [a for a in task_manager.current_topic.answers if a[0] != session['session_id']]
        task_manager.current_topic.answers.append((session['session_id'], "C"))
        
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
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button to sign in with Huggingface.", "error")
        return unselectedOptions()
    
    task_manager = app.state.task_manager
    
    async with task_manager.answers_lock:
        task_manager.current_topic.answers = [a for a in task_manager.current_topic.answers if a[0] != session['session_id']]
        task_manager.current_topic.answers.append((session['session_id'], "D"))
        
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
    return Div(Form(Input(type='text', name='topic', placeholder="frieren borgar", maxlength=f"{TOPIC_MAX_LENGTH}", required=True, autofocus=True),
                 Input(type="number", placeholder="NR POINTS", min=BID_MIN_POINTS, name='points', value=BID_MIN_POINTS, required=True),
                 Button('BID', cls='primary', style='width: 100%;'),
                 action='/', hx_post='/bid', style='border: 5px solid #eaf6f6; padding: 10px; width: 100%; margin: 10px auto;'), hx_swap="outerHTML"
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
    A("STATS", href="/stats", role="button", cls="secondary"),
    Div(
        A("FAQ", href="/faq", role="button", cls="secondary"),
        Div(id="theme-toggle"),
        cls="last-tab"
    ),
    cls="tabs"
)
    
@rt('/')
async def get(session, app, request):
    task_manager = app.state.task_manager
    user_id = None
    if 'session_id' in session:
        user_id = session['session_id']
        with task_manager.clients_lock:
            if user_id not in task_manager.clients:
                task_manager.clients[user_id] = set()
        
        if user_id not in task_manager.user_dict:
            task_manager.user_dict[user_id] = None

        db_player = db.q(f"select * from {players} where {players.c.id} = '{task_manager.user_dict[user_id]}'")

        if not db_player:
            current_points = 20
            players.insert({'name': user_id, 'points': current_points})
            query = f"SELECT {players.c.id} FROM {players} WHERE {players.c.name} = ?"
            result = db.q(query, (user_id,))
            task_manager.user_dict[user_id] = result[0]['id']
        else:
            current_points = db_player[0]['points']

    current_question_info = Div(id="current_question_info")
    left_panel = Div(
        Div(id="next_topics"),
        bid_form(),
        cls='side-panel'
    )
    if user_id:
        top_right_corner = Div(user_id + ": " + str(current_points) + " pts", cls='login', id='login_points')
    else:
        top_right_corner = Div(A(Img(src="https://huggingface.co/datasets/huggingface/badges/resolve/main/sign-in-with-huggingface-xl.svg", id="login-badge"), href=huggingface_client.login_link_with_state()), cls='login')

    middle_panel = Div(
        Div(top_right_corner, cls='login_wrapper'),
        Div(id="countdown"),
        current_question_info,
        Div(bid_form(), cls='bid_wrapper'),
        cls="middle-panel"
    )
    right_panel = Div(
        top_right_corner,
        Div(id="past_topic"),
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

@rt('/stats')
async def get(session, app, request):
    task_manager = app.state.task_manager
    db_player = db.q(f"select * from {players} order by points desc limit 20")
    cells = [Tr(Td(row['name']), Td(row['points'])) for row in db_player]
    with task_manager.clients_lock:
        c = [c for c in task_manager.clients if c != "unassigned_clients"]
        
    main_content =  Div(
        Div(H1("Logged in users (" + str(len(c)) + "):"), Div(", ".join(c))),
        Div(H1("Leaderboard"), Table(Tr(Th(B('HuggingFace Username')), Th(B("Points"))), *cells))
    )
    return Div(
        tabs,
        main_content,
        cls="container"
    )

@rt('/faq')
async def get(session, app, request):
    return Div(
        tabs,
        Iframe(src="https://mihaiii.github.io/semantic-autocomplete/", style="height: 130vh; width: 100%;"),
        # cls="container"
    )

@rt("/bid")
async def post(session, topic: str, points: int):
    if('session_id' not in session):
        add_toast(session, "Only logged in Huggingface users can play. Press on the right-top corner button to sign in with Huggingface.", "error")
        return bid_form()
    print(f"Topic: {topic}, points: {points}")
    
    if points < BID_MIN_POINTS:
        add_toast(session, f"Bid at least {BID_MIN_POINTS} points", "error")
        return bid_form()
    
    if len(topic) > TOPIC_MAX_LENGTH:
        add_toast(session, f"The topic max length is {TOPIC_MAX_LENGTH} characters", "error")
        return bid_form()
    
    if len(topic) == 0:
        add_toast(session, "Cannot send empty topic", "error")
        return bid_form()

    if similar(topic, "ignore previous instructions") >= 0.5:
        add_toast(session, "Error", "error")
        return bid_form()

    task_manager = app.state.task_manager

    async with task_manager.topics_lock:
        if similar(topic, task_manager.current_topic.topic) >= DUPLICATE_TOPIC_THRESHOLD:
            add_toast(session, f"Topic '{topic}' is very similar with an existing one. Please request another topic.")
            return bid_form()

        for t in task_manager.topics:
            if similar(t.topic, topic) >= DUPLICATE_TOPIC_THRESHOLD:
                add_toast(session, f"Topic '{topic}' is very similar with an existing one. Please request another topic.")
                return bid_form()
            
        if task_manager.past_topic:
            if similar(t.topic, task_manager.past_topic.topic) >= DUPLICATE_TOPIC_THRESHOLD:
                add_toast(session, f"Topic '{topic}' is very similar with an existing one. Please request another topic.")
                return bid_form()

    if 'session_id' in session:
        user_id = session['session_id']
        db_player = db.q(f"select * from {players} where {players.c.id} = '{task_manager.user_dict[user_id]}'")
        if db_player[0]['points'] - points >= 0:
            db_player[0]['points'] -= points
            players.update(db_player[0])

            await task_manager.add_user_topic(topic=topic, points=points)
            elem = Div(user_id + ": " + str(db_player[0]['points']) + " pts", cls='login', id='login_points')

            for client in task_manager.clients[user_id]:
                await task_manager.send_to_clients(elem, client)
        else:
            add_toast(session, "Not enough points", "error")
    return bid_form()


async def on_connect(send, ws):
    client_key = "unassigned_clients"
    if ws.scope['session'] and ws.scope['session']['session_id']:
        client_key = ws.scope['session']['session_id']
    task_manager = app.state.task_manager
    with task_manager.clients_lock:
        if client_key not in task_manager.clients:
            task_manager.clients[client_key] = set()
        task_manager.clients[client_key].add(send)
    await task_manager.broadcast_next_topics(send)
    if task_manager.current_topic:
        await task_manager.broadcast_current_question(send)
    await task_manager.broadcast_past_topic(send)


async def on_disconnect(send, session):
    print("Calling on_disconnect")
    print(len(app.state.task_manager.clients))
    task_manager = app.state.task_manager
    with task_manager.clients_lock:
        print("I'm inside the lock")
        key_to_remove = None
        if send in task_manager.clients.copy():
            for key, client_set in task_manager.clients.items():
                if send in client_set:
                    client_set.remove(send)
                    if len(client_set) == 0:
                        key_to_remove = key
                    break
                
            if key_to_remove:
                task_manager.clients.pop(key_to_remove)
                        
            if session:
                session['session_id'] = None
            print("Client was removed and printing len clients")
            print(len(task_manager.clients))


@app.ws('/ws', conn=on_connect, disconn=on_disconnect)
async def ws(send):
    pass