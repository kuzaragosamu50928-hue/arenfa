# Geneva Project

This project is a Telegram-based application for facilitating housing rentals and requests. It consists of two Telegram bots and a web-based administration panel.

-   **Hunter Bot**: The user-facing bot for submitting and managing rental listings and requests.
-   **Moderator Bot**: An internal bot for administrators to manage submissions, view stats, and publish listings.
-   **Admin Panel**: A web interface for moderators to review, approve, or reject submissions.
-   **Public Map**: A web page that visually displays all approved rental listings on a map.

## Tech Stack

-   **Backend**: Python, `aiohttp` (web server), `pyTelegramBotAPI` (Telegram bots)
-   **Database**: `aiosqlite` (asynchronous SQLite)
-   **Frontend**: HTML, Tailwind CSS (via CDN), Vanilla JavaScript
-   **Containerization**: Docker, Docker Compose

## Project Structure

The project is structured for modularity and maintainability:

```
.
├── src/
│   ├── bots/
│   │   ├── __init__.py
│   │   ├── hunter.py       # Logic for the user-facing bot
│   │   └── moderator.py    # Logic for the admin bot
│   ├── web/
│   │   ├── __init__.py
│   │   ├── handlers.py     # aiohttp request handlers
│   │   └── routes.py       # URL route definitions
│   ├── config.py           # Configuration loader from environment variables
│   └── database.py         # Asynchronous database logic
├── admin_panel.html        # Frontend for the admin moderation panel
├── public_map.html         # Frontend for the public map view
├── main.py                 # Main application entry point
├── Dockerfile              # Docker build instructions
├── docker-compose.yml      # Docker Compose service definition
├── requirements.txt        # Production Python dependencies
├── requirements-dev.txt    # Development/testing dependencies
├── .env.example            # Template for environment variables
└── .gitignore              # Specifies intentionally untracked files
```

## Getting Started

### Prerequisites

-   Docker
-   Docker Compose

### Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Create the environment file:**
    Copy the example environment file and fill in your specific values.
    ```bash
    cp .env.example .env
    ```
    Now, edit the `.env` file with your Telegram bot tokens, channel ID, admin ID, and domain name.

3.  **Build and run the application:**
    Use Docker Compose to build and run the application in detached mode.
    ```bash
    docker compose up -d --build
    ```
    The application will be accessible at the domain you configured, and the admin panel will be at `http://<your-domain>/admin`.

## Development

To install dependencies for local development or testing:

```bash
pip install -r requirements-dev.txt
```
This includes tools like `playwright` for frontend testing.