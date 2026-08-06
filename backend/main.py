import os

import uvicorn

from backend.app import app, create_app


def main():
    uvicorn.run(
        "backend.app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "4173")),
        reload=False,
    )


if __name__ == "__main__":
    main()
