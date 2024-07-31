import json

async def gen_topics():
    return ["cat", "dog"]
    
async def topic_check(topic):
    return "Yes"

async def generate_question(topic):
    content = {"trivia question": "Trivia q",
    "option A": "op a",
    "option B": "op b",
    "option C": "op c",
    "option D": "ob d",
    "correct answer": "option D"}
    return content
    
