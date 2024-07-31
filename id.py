import random


class IDGenerator:
    def __init__(self):
        self.used_ids = set()

    def generate_random_id(self):
        while True:
            id_candidate = random.randint(1000, 99999)
            if id_candidate not in self.used_ids:
                self.used_ids.add(id_candidate)
                return f"#{str(id_candidate)}"
