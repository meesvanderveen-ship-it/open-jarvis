from dotenv import load_dotenv
import os

load_dotenv()

secret = os.getenv("COINBASE_API_SECRET")
print("SECRET AANWEZIG:", secret is not None)
print("LENGTE:", len(secret) if secret else 0)
print("HEEFT BEGIN EC:", "BEGIN EC PRIVATE KEY" in secret if secret else False)
print("HEEFT END EC:", "END EC PRIVATE KEY" in secret if secret else False)
print("AANTAL LITERAL \\n:", secret.count("\\n") if secret else 0)
