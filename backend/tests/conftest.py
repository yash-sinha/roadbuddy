import os

# Provide dummy env vars so modules can be imported without real keys
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("DEEPGRAM_API_KEY", "test-key")
os.environ.setdefault("CARTESIA_API_KEY", "test-key")
