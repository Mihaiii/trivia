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

logging.basicConfig(level=logging.DEBUG)

QUESTION_COUNTDOWN_SEC = 5  # HOW MUCH TIME USERS HAVE TO ANSWER THE QUESTION? IN PROD WILL PROBABLY BE 18 or 20.
KEEP_FAILED_TOPIC_SEC = 5  # NUMBER OF SECONDS TO KEEP THE FAILED TOPIC IN THE UI (USER INTERFACE) BEFORE REMOVING IT FROM THE LIST
MAX_TOPIC_LENGTH_CHARS = 30  # DON'T ALLOW USER TO WRITE LONG TOPICS
MAX_NR_TOPICS_FOR_ALLOW_MORE = 6  # AUTOMATICALLY ADD TOPICS IF THE USERS DON'T BID/PROPOSE NEW ONES
NR_TOPICS_TO_BROADCAST = 5  # NUMBER OF TOPICS TO APPEAR IN THE UI. THE ACTUAL LIST CAN CONTAIN MORE THAN THIS.
BID_MIN_POINTS = 3  # MINIMUM NUMBER OF POINTS REQUIRED TO PLACE A TOPIC BID IN THE UI

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
    Style('.side-panel { display: flex; flex-direction: column; width: 20%; padding: 10px; border-right: 1px solid #ddd; }'),
    Style('.middle-panel { display: flex; flex-direction: column; flex: 1; padding: 10px; }'),
    Style('@media (max-width: 768px) { .main { flex-direction: column; } .left-panel { width: 100%; border-right: none; border-bottom: 1px solid #ddd; } .right-panel { width: 100%; } }'),
    Style('.primary:active { background-color: #0056b3; }')
]
countdown = QUESTION_COUNTDOWN_SEC


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
        self.users_lock = asyncio.Lock()
        self.executors = [concurrent.futures.ThreadPoolExecutor(max_workers=1) for _ in range(num_executors)]
        self.executor_tasks = [set() for _ in range(num_executors)]
        self.current_topic_start_time = None
        self.users = {}  # Track if users have chosen an option
        self.user_points = {}  # Track user points
        self.current_timeout_task = None
        self.clients = set()  # Track connected WebSocket clients
        self.clients_lock = threading.Lock()
        self.task = None
        self.countdown_var = None

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
        global current_topic
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

            if topic.status == "successful" and current_topic is None:
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
        global current_topic
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
                current_topic = topic
                self.current_topic_start_time = asyncio.get_event_loop().time()
                self.current_timeout_task = asyncio.create_task(self.topic_timeout())
                async with self.users_lock:
                    self.users = {user: False for user in self.users.keys()}  # Reset user choices
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
        global current_topic
        should_consume = False
        async with self.users_lock:
            all_users_chosen = all(self.users.values())
        logging.debug("check_topic_completion before self.topics_lock")
        async with self.topics_lock:
            logging.debug("check_topic_completion after self.topics_lock")
            current_time = asyncio.get_event_loop().time()
            logging.debug(current_time)
            logging.debug(self.current_topic_start_time)
            if current_topic and (
                    current_time - self.current_topic_start_time >= QUESTION_COUNTDOWN_SEC - 0.4 or all_users_chosen):
                logging.debug(f"Completing topic: {current_topic.topic}")
                should_consume = True
        if should_consume:
            if self.task:
                self.task.cancel()
                self.reset()
            self.task = asyncio.create_task(self.count())
            async with self.past_topics_lock:
                self.past_topics.append(current_topic)
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
        with self.clients_lock:
            print("self.clients len")
            print(len(self.clients))
            clients = self.clients if client is None else [client]
            for client in clients.copy():
                try:
                    await client(Div(*next_topics_html, id="next_topics"))
                except:
                    self.clients.remove(client)
                    logging.debug(f"Removed disconnected client: {client}")
        # logging.debug("Broadcasting top topics")

    async def broadcast_past_topics(self, client=None):
        global current_topic
        async with self.past_topics_lock:
            past_topics = list(self.past_topics)[::-1]
        past_topics_html = [Div(f"{item.topic} - {item.user} - {', '.join(item.winners)}", cls="card") for item in
                            past_topics]
        with self.clients_lock:
            clients = self.clients if client is None else [client]
            for client in clients.copy():
                try:
                    await client(Div(*past_topics_html, id="past_topics"))
                except:
                    self.clients.remove(client)
                    logging.debug(f"Removed disconnected client: {client}")
            # logging.debug("Broadcasting past topics")

    async def broadcast_current_question(self, client=None):
        current_question_info = Div(
            Div(
                Div(current_topic.question.title, style="font-size: 30px;"),
                Div(current_topic.user, cls="item left"),
                Div(f"{current_topic.points} pts", cls="item right"),
                cls="card"),
            Div(
                Button(current_topic.question.option_A, cls="primary", hx_post="/choose_option_A",
                       hx_target="#question_options", hx_swap="outerHTML"),
                Button(current_topic.question.option_B, cls="primary", hx_post="/choose_option_B",
                       hx_target="#question_options", hx_swap="outerHTML"),
                Button(current_topic.question.option_C, cls="primary", hx_post="/choose_option_C",
                       hx_target="#question_options", hx_swap="outerHTML"),
                Button(current_topic.question.option_D, cls="primary", hx_post="/choose_option_D",
                       hx_target="#question_options", hx_swap="outerHTML"),
                cls="options",
                style="display: flex; flex-direction: column; gap: 10px; ",
                id="question_options"
            )
        )
        with self.clients_lock:
            clients = self.clients if client is None else [client]
            for client in clients.copy():
                try:
                    await client(Div(current_question_info, id="current_question_info"))
                except:
                    self.clients.remove(client)
                    logging.debug(f"Removed disconnected client: {client}")

    async def count(self):
        global countdown
        countdown = QUESTION_COUNTDOWN_SEC
        # await self.consume_successful_topic()
        while countdown >= 0:
            await self.broadcast_countdown()
            await asyncio.sleep(1)
            countdown -= 1

    async def broadcast_countdown(self, client=None):
        global countdown
        countdown_div = Div(f"COUNTDOWN: {countdown}s", cls="countdown")
        with self.clients_lock:
            clients = self.clients if client is None else [client]
            for client in clients.copy():
                try:
                    await client(Div(countdown_div, id="countdown"))
                except:
                    self.clients.remove(client)
                    logging.debug(f"Removed disconnected client: {client}")


async def app_startup():
    num_executors = 2  # Change this to run more executors
    task_manager = TaskManager(num_executors)
    app.state.task_manager = task_manager
    asyncio.create_task(task_manager.monitor_topics())
    for i in range(num_executors):
        asyncio.create_task(task_manager.run_executor(i))


app = FastHTML(hdrs=(css), ws_hdr=True, on_startup=[app_startup], debug=True)
rt = app.route


@rt('/choose_option_A')
async def post(request):
    global current_topic
    # TODO: save the user's choice based on the login data - this will be implemented after auth is implemented
    return Div(
        Button(current_topic.question.option_A, cls="primarly", hx_post="/choose_option_A",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_B, cls="secondary", hx_post="/choose_option_B",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_C, cls="secondary", hx_post="/choose_option_C",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_D, cls="secondary", hx_post="/choose_option_D",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        cls="options",
        style="display: flex; flex-direction: column; gap: 10px; ",
        id="question_options"
    )


@rt('/choose_option_B')
async def post(request):
    global current_topic
    # TODO: save the user's choice based on the login data - this will be implemented after auth is implemented
    return Div(
        Button(current_topic.question.option_A, cls="secondary", hx_post="/choose_option_A",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_B, cls="primarly", hx_post="/choose_option_B",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_C, cls="secondary", hx_post="/choose_option_C",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_D, cls="secondary", hx_post="/choose_option_D",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        cls="options",
        style="display: flex; flex-direction: column; gap: 10px; ",
        id="question_options"
    )


@rt('/choose_option_C')
async def post(request):
    global current_topic
    # TODO: save the user's choice based on the login data - this will be implemented after auth is implemented
    return Div(
        Button(current_topic.question.option_A, cls="secondary", hx_post="/choose_option_A",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_B, cls="secondary", hx_post="/choose_option_B",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_C, cls="primarly", hx_post="/choose_option_C",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_D, cls="secondary", hx_post="/choose_option_D",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        cls="options",
        style="display: flex; flex-direction: column; gap: 10px; ",
        id="question_options"
    )


@rt('/choose_option_D')
async def post(request):
    global current_topic
    # TODO: save the user's choice based on the login data - this will be implemented after auth is implemented
    return Div(
        Button(current_topic.question.option_A, cls="secondary", hx_post="/choose_option_A",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_B, cls="secondary", hx_post="/choose_option_B",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_C, cls="secondary", hx_post="/choose_option_C",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        Button(current_topic.question.option_D, cls="primarly", hx_post="/choose_option_D",
               hx_target="#question_options", hx_swap="outerHTML", disabled=True),
        cls="options",
        style="display: flex; flex-direction: column; gap: 10px; ",
        id="question_options"
    )


@rt('/')
async def get(request):
    global countdown
    tabs = Nav(
        A("PLAY", href="#", role="button", cls="secondary"),
        A("LEADERBOARD", href="#", role="button", cls="secondary"),
        A("FAQ", href="#", role="button", cls="secondary"),
        cls="tabs"
    )

    countdown_div = Div(id="countdown")
    current_question_info = Div(id="current_question_info")
    left_panel = Div(
        Div(id="next_topics"),
        Div(Form(Input(type='text', name='topic', placeholder="TOPIC"),
                 Input(type="number", placeholder="NR POINTS", min=BID_MIN_POINTS, name='points'),
                 Button('BID', cls='primary'),
                 action='/', hx_post='/bid'), hx_swap="outerHTML"
            )
        , cls='side-panel'
    )
    middle_panel = Div(
        countdown_div,
        current_question_info,
        cls="middle-panel"
    )

    right_panel = Div(
        Button("Login / nr of points", cls="primary"),
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


@rt("/bid")
async def post(topic: str, points: int):
    print(f"Topic: {topic}, points: {points}")
    task_manager = app.state.task_manager
    await task_manager.add_user_topic(topic=topic, points=points)
    return Div(Form(Input(type='text', name='topic', placeholder="TOPIC"),
                    Input(type="number", placeholder="NR POINTS", min=BID_MIN_POINTS, name='points'),
                    Button('BID', cls='primary'),
                    action='/', hx_post='/bid'), hx_swap="outerHTML"
               )


async def on_connect(send, ws):
    global current_topic
    task_manager = app.state.task_manager
    with task_manager.clients_lock:
        task_manager.clients.add(send)
    user_id = f"user_{random.randint(1000, 9999)}"  # Simulated user identification
    task_manager.users[user_id] = False
    if user_id not in task_manager.user_points:
        task_manager.user_points[user_id] = 20  # Initialize user with 20 points
    logging.info(f"Client connected: {user_id}")
    ws.scope['user_id'] = user_id
    ws.scope['task_manager'] = task_manager
    await task_manager.broadcast_next_topics(send)
    if current_topic:
        await task_manager.broadcast_current_question(send)
    await task_manager.broadcast_past_topics(send)


async def on_disconnect(send, ws):
    print("Calling on_disconnect")
    print(len(app.state.task_manager.clients))
    task_manager = app.state.task_manager
    with task_manager.clients_lock:
        print("I'm inside the lock")
        if send in task_manager.clients.copy():
            task_manager.clients.remove(send)
            print("Client was removed and printing len clients")
            print(len(task_manager.clients))
    logging.info(f"Client disconnected: {ws.scope['user_id']}")


@app.ws('/ws', conn=on_connect, disconn=on_disconnect)
async def ws(send):
    pass


run_uv()