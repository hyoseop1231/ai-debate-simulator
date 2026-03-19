"""Entry point for the AI Debate Simulator v2 API server."""

import uvicorn


def main() -> None:
    """Run the FastAPI application via uvicorn."""
    uvicorn.run(
        "api.app:app",
        host="0.0.0.0",
        port=8003,
        reload=True,
    )


if __name__ == "__main__":
    main()
