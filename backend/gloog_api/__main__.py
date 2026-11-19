import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser(description="Gloog backend + dashboard")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    print(f"[gloog] dashboard + API on http://localhost:{a.port}  (UDP CSI 5501, band 5600)")
    uvicorn.run("gloog_api.main:app", host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
