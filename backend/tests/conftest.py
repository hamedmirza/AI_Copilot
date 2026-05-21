import os

# Isolate API tests from production app.db (engine binds at import time).
os.environ["DB_URL"] = "sqlite:///./backend/test_app.db"
