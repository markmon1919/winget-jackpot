import time
import threading

class TokenManager:
    def __init__(self):
        self._token = None
        self._lock = threading.Lock()
        self._updated_at = 0

    def set_token(self, token: str):
        with self._lock:
            self._token = token
            self._updated_at = time.time()

    def get_token(self):
        with self._lock:
            return self._token

    def is_valid(self, ttl=600):
        return self._token is not None and (time.time() - self._updated_at) < ttl


token_manager = TokenManager()