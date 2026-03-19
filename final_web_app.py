"""Thin entry point -- delegates to api.app for the FastAPI application."""

from api.app import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8003)
