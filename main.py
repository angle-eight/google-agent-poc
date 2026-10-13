"""Start the helpdesk web application."""

import os

import uvicorn


def main():
    uvicorn.run("helpdesk.web:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))


if __name__ == "__main__":
    main()
