# agent/context/history.py
"""In-memory session history (simple list)."""


class History:
    def __init__(self):
        self.messages = []

    def append(self, message):
        self.messages.append(message)

    def recent(self, n: int = 8):
        return self.messages[-n:]

    def __iter__(self):
        return iter(self.messages)
