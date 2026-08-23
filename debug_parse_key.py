from dotenv import load_dotenv
import os
from cryptography.hazmat.primitives import serialization

load_dotenv()

secret = os.getenv("COINBASE_API_SECRET")
clean = (secret or "").replace("\\n", "\n").strip()

print("SECRET AANWEZIG:", bool(clean))
print("AANTAL ECHTE NEWLINES:", clean.count("\n"))

if not clean:
    raise SystemExit("COINBASE_API_SECRET ontbreekt")

key = serialization.load_pem_private_key(
    clean.encode("utf-8"),
    password=None,
)

print("KEY OK:", type(key))
