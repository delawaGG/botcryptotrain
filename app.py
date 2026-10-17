"""app.py — Dispatcher: pilih mode spot atau futures."""
import os, sys
from dotenv import load_dotenv
load_dotenv()


def main():
    mode = os.getenv("TRADING_MODE", "futures").strip().lower()
    if mode == "spot":
        from bot_spot import main as run
    elif mode == "futures":
        from bot_futures import main as run
    else:
        print(f"❌ TRADING_MODE tidak dikenal: {mode}")
        sys.exit(1)
    run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutdown.")
