import asyncio
import concurrent.futures
import random
import websockets
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import List, Set, Deque, Dict
QUESTION_COUNTDOWN_SEC = 20
KEEP_FAILED_TOPIC_SEC = 5
MAX_TOPIC_LENGTH_CHARS = 30
MAX_NR_TOPICS_ALLOW_MORE = 10
NR_TOPICS_TO_BREADCAST = 5

logging.basicConfig(level=logging.DEBUG)

@dataclass(order=True)
class Topic:
    points: int
    topic: str = field(compare=False)
    status: str = field(default="pending", compare=False)
    user: str = field(default="[bot]", compare=False)
    
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
        self.users_lock = asyncio.Lock()
        self.executors = [concurrent.futures.ThreadPoolExecutor(max_workers=1) for _ in range(num_executors)]
        self.executor_tasks = [set() for _ in range(num_executors)]
        self.current_topic = None
        self.current_topic_start_time = None
        self.users = {}  # Track if users have chosen an option
        self.user_points = {}  # Track user points
        self.current_timeout_task = None
        self.clients = set()  # Track connected WebSocket clients

    async def add_default_topics(self):
        async with self.topics_lock:
            if len(self.topics) < MAX_NR_TOPICS_ALLOW_MORE:
                for i in range(10):
                    self.topics.append(Topic(0, f"Default Topic {i}", user="[bot]"))
                self.topics = deque(sorted(self.topics, reverse=True))
                await self.broadcast_top_topics()
        logging.debug("Default topics added")

    async def add_topic(self, topic: str, points: int, user: str):
        if len(topic) > MAX_TOPIC_LENGTH_CHARS:
            return {"error": "Topic is longer than 30 characters"}
        async with self.topics_lock:
            if self.user_points.get(user, 0) < points:
                return {"error": "User does not have enough points"}
            self.user_points[user] -= points
            self.topics.append(Topic(points, topic, user=user))
            self.topics = deque(sorted(self.topics, reverse=True))
            await self.broadcast_top_topics()
            logging.debug(f"Topic added: {topic} by {user}")
            return {"success": "Topic added"}

    async def update_status(self, topic: Topic):
        await asyncio.sleep(1)  # Simulate processing time
        should_consume = False
        async with self.topics_lock:
            if topic.status == "pending":
                topic.status = random.choice(["computing"]) #TODO: ["computing", "failed"]
            elif topic.status == "computing":
                topic.status = random.choice(["successful"]) #TODO: ["successful", "failed"]
            
            await self.broadcast_top_topics()

            if topic.status == "successful" and self.current_topic is None:
                should_consume = True
            
            if topic.status == "failed":
                await asyncio.create_task(self.remove_failed_topic(topic))
            
            logging.debug(f"Topic updated: {topic.topic} to {topic.status}")
        
        if should_consume:
            await self.consume_successful_topic()

    async def remove_failed_topic(self, topic: Topic):
        await asyncio.sleep(KEEP_FAILED_TOPIC_SEC)
        async with self.topics_lock:
            if topic in self.topics and topic.status == "failed":
                self.topics.remove(topic)
                await self.broadcast_top_topics()
        logging.debug(f"Failed topic removed: {topic.topic}")

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

    async def monitor_topics(self):
        while True:
            need_default_topics = False
            async with self.topics_lock:
                if all(topic.status in ["successful", "failed"] for topic in self.topics):
                    need_default_topics = True

            if need_default_topics:
                await self.add_default_topics()
            
            await asyncio.sleep(1)  # Check periodically

    async def consume_successful_topic(self):
        topic = None
        logging.debug(f"consume_successful_topic before lock")
        async with self.topics_lock:
            logging.debug(f"consume_successful_topic after lock")
            successful_topics = [t for t in self.topics if t.status == "successful"]
            logging.debug(successful_topics)
            if successful_topics:
                topic = successful_topics[0]  # Get the highest points successful topic
                logging.debug(f"Topic obtained: {topic.topic}")
                self.topics.remove(topic)
                self.current_topic = topic
                self.current_topic_start_time = asyncio.get_event_loop().time()
                async with self.users_lock:
                    self.users = {user: False for user in self.users.keys()}  # Reset user choices
                #if self.current_timeout_task:
                #    self.current_timeout_task.cancel()  # Cancel any existing timeout task
                self.current_timeout_task = asyncio.create_task(self.topic_timeout())  # Start the 20-second timeout
                
        if topic:
            logging.debug(f"We have a topic to broadcast: {topic.topic}")
            await self.broadcast_current_topic()
            await self.broadcast_top_topics()
            logging.debug(f"Topic consumed: {topic.topic}")
        return topic

    async def topic_timeout(self):
        try:
            await asyncio.sleep(QUESTION_COUNTDOWN_SEC)  # Wait for 20 seconds
            await self.check_topic_completion()  # Check if the topic should be completed
            logging.debug(f"{QUESTION_COUNTDOWN_SEC} seconds timeout completed")
        except asyncio.CancelledError:
            logging.debug("Timeout task cancelled")
            pass  # Handle cancellation if the task is cancelled

    async def check_topic_completion(self):
        should_consume = False
        current_time = asyncio.get_event_loop().time()
        async with self.users_lock:
            all_users_chosen = all(self.users.values())
        logging.debug("check_topic_completion before self.topics_lock")
        async with self.topics_lock:
            logging.debug("check_topic_completion after self.topics_lock")
            logging.debug(current_time)
            logging.debug(self.current_topic_start_time)
            if self.current_topic and (current_time - self.current_topic_start_time >= 20 or all_users_chosen):
                logging.debug(f"Completing topic: {self.current_topic.topic}")
                should_consume = True
        
        if should_consume:
            await self.consume_successful_topic()

    async def user_choice(self, user: str):
        async with self.users_lock:
            self.users[user] = True
            logging.debug(f"User {user} made a choice")
            if all(self.users.values()):
                #if self.current_timeout_task:
                #    self.current_timeout_task.cancel()  # Cancel the timeout task if all users have chosen
                await self.check_topic_completion()  # Immediately check if all users have chosen

    async def broadcast_current_topic(self):
        if self.current_topic:
            message = json.dumps({
                "current_topic": self.current_topic.topic,
                "points": self.current_topic.points,
                "user": self.current_topic.user
            })
            await asyncio.gather(*(client.send(message) for client in self.clients))
            logging.debug(f"Broadcasting current topic: {self.current_topic.topic}")

    async def broadcast_top_topics(self):
        top_topics = list(self.topics)[:NR_TOPICS_TO_BREADCAST]
        message = json.dumps({
            "top_topics": [
                {"topic": t.topic, "points": t.points, "status": t.status, "user": t.user}
                for t in top_topics
            ]
        })
        await asyncio.gather(*(client.send(message) for client in self.clients))
        logging.debug("Broadcasting top topics")

async def consumer_handler(websocket, task_manager):
    user_id = websocket.remote_address[0]  # Simplified user identification
    task_manager.clients.add(websocket)
    task_manager.users[user_id] = False
    if user_id not in task_manager.user_points:
        task_manager.user_points[user_id] = 100  # Initialize user with 100 points
    logging.info(f"Client connected: {user_id}")
    try:
        async for message in websocket:
            data = json.loads(message)
            topic = data.get('topic')
            points = data.get('points', 0)
            if topic:
                response = await task_manager.add_topic(topic, points, user_id)
                await websocket.send(json.dumps(response))
            elif data.get('action') == 'consume':
                consumed_topic = await task_manager.consume_successful_topic()
                if consumed_topic:
                    await websocket.send(json.dumps({
                        "consumed_topic": consumed_topic.topic,
                        "points": consumed_topic.points,
                        "user": consumed_topic.user
                    }))
                else:
                    await websocket.send(json.dumps({
                        "message": "No successful topic to consume"
                    }))
            elif data.get('action') == 'choose':
                await task_manager.user_choice(user_id)
    finally:
        task_manager.clients.remove(websocket)
        logging.info(f"Client disconnected: {user_id}")

async def server(task_manager):
    async with websockets.serve(lambda ws, path: consumer_handler(ws, task_manager), "localhost", 8765):
        await asyncio.Future()  # run forever

async def main():
    num_executors = 2  # Change this to run more executors
    task_manager = TaskManager(num_executors)
    #todo: uncomments
    #asyncio.create_task(task_manager.monitor_topics())
    for i in range(num_executors):
        asyncio.create_task(task_manager.run_executor(i))
    await server(task_manager)

if __name__ == "__main__":
    asyncio.run(main())
