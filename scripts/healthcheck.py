"""Check this instance after a restart; exits nonzero on unavailable/malformed state."""
import json
import os
import sys
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
host = os.getenv("APP_HOST", "0.0.0.0")
if host == "0.0.0.0":
    host = "127.0.0.1"
try:
    with urllib.request.urlopen(f"http://{host}:{os.getenv('APP_PORT', '5000')}/api/state", timeout=5) as response:
        state = json.load(response)
    print("App reachable; phase=" + state["security"]["phase"] + "; CAN=" + str(state["can_up"]))
except (OSError, ValueError, KeyError) as error:
    print("Health check failed: " + str(error), file=sys.stderr)
    sys.exit(1)
