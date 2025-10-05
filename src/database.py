"""
Database module for asynchronous operations with aiosqlite.

This module handles all interactions with the SQLite database, including:
- Initializing the database and tables.
- Managing user session states for the conversation flow.
- Handling submissions, pending publications, and final listings.
"""
import aiosqlite
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from .config import DB_PATH, logger

# --- Database Initialization ---

import os


async def init_db() -> None:
    """
    Asynchronously initializes the database.

    Creates all required tables if they do not already exist.
    It assumes the parent directory for the DB file already exists.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                step TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id TEXT UNIQUE NOT NULL,
                submission_type TEXT NOT NULL,
                data TEXT NOT NULL,
                user_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS pending_publication (
                user_id INTEGER PRIMARY KEY,
                submission_type TEXT NOT NULL,
                data TEXT NOT NULL
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id TEXT UNIQUE NOT NULL,
                listing_type TEXT NOT NULL,
                data TEXT NOT NULL,
                message_id INTEGER,
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()
        logger.info("Database 'Женева' successfully initialized.")

# --- User State Management ---

async def get_user_state(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Asynchronously retrieves the state for a given user.

    Args:
        user_id: The Telegram user ID.

    Returns:
        A dictionary containing the user's 'step' and 'data', or None if not found.
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT step, data FROM user_sessions WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {'step': row[0], 'data': json.loads(row[1])}
    except Exception as e:
        logger.error(f"Error getting state for user {user_id}: {e}")
    return None

async def set_user_state(user_id: int, step: str, data: Dict[str, Any]) -> None:
    """
    Asynchronously saves or updates a user's state.

    Args:
        user_id: The Telegram user ID.
        step: The current step in the conversation flow.
        data: A dictionary of data to be saved for the user.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_sessions (user_id, step, data, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (user_id, step, json.dumps(data, ensure_ascii=False))
        )
        await db.commit()

async def clear_user_state(user_id: int) -> None:
    """
    Asynchronously clears the state for a given user.

    Args:
        user_id: The Telegram user ID.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        await db.commit()

# --- Submission and Listing Management ---

async def save_submission_to_db(submission_id: str, submission_type: str, data: Dict[str, Any], user_id: int) -> None:
    """
    Asynchronously saves a new submission to the database.

    Args:
        submission_id: A unique identifier for the submission.
        submission_type: The type of submission (e.g., 'rent_offer_long_term').
        data: The submission data as a dictionary.
        user_id: The ID of the user making the submission.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO submissions (submission_id, submission_type, data, user_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (submission_id, submission_type, json.dumps(data, ensure_ascii=False), user_id, datetime.now())
        )
        await db.commit()

async def get_last_submission_time(user_id: int) -> Optional[datetime]:
    """
    Asynchronously gets the timestamp of a user's last submission.

    Args:
        user_id: The Telegram user ID.

    Returns:
        A datetime object of the last submission, or None if no submissions exist.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT created_at FROM submissions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                try:
                    return datetime.fromisoformat(row[0])
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse date format: {row[0]}")
    return None

async def add_listing(submission_id: str, listing_type: str, data: Dict[str, Any], message_id: int) -> None:
    """
    Asynchronously saves a published listing to the database.

    Args:
        submission_id: The unique ID for the new listing.
        listing_type: The type of listing.
        data: The listing data as a dictionary.
        message_id: The message ID of the post in the Telegram channel.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO listings (submission_id, listing_type, data, message_id) VALUES (?, ?, ?, ?)",
            (submission_id, listing_type, json.dumps(data, ensure_ascii=False), message_id)
        )
        await db.commit()

# --- Functions for Web Handlers ---

async def get_all_submissions() -> Dict[str, Dict[str, Any]]:
    """Fetches all submissions pending moderation."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT submission_id, submission_type, data FROM submissions ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
            return {row[0]: {'type': row[1], 'data': json.loads(row[2])} for row in rows}

async def get_rent_offer_listings() -> Dict[str, Dict[str, Any]]:
    """Fetches all published rent offer listings."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT submission_id, listing_type, data FROM listings WHERE listing_type LIKE 'rent_offer_%'") as cursor:
            rows = await cursor.fetchall()
            return {row[0]: {'type': row[1], 'data': json.loads(row[2])} for row in rows}

async def get_db_stats() -> Dict[str, int]:
    """Fetches statistics from the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM submissions") as cursor:
            pending_count = (await cursor.fetchone() or [0])[0]
        async with db.execute("SELECT COUNT(*) FROM listings") as cursor:
            active_count = (await cursor.fetchone() or [0])[0]
        async with db.execute("SELECT COUNT(*) FROM listings WHERE date(published_at) = date('now')") as cursor:
            today_count = (await cursor.fetchone() or [0])[0]
        return {
            'pending_count': pending_count,
            'active_count': active_count,
            'today_count': today_count
        }

async def get_submission_by_id(submission_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves a single submission by its ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT submission_type, data FROM submissions WHERE submission_id=?", (submission_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {'type': row[0], 'data': json.loads(row[1])}
    return None

async def delete_submission(db: aiosqlite.Connection, submission_id: str) -> None:
    """Deletes a submission from the database."""
    await db.execute("DELETE FROM submissions WHERE submission_id=?", (submission_id,))

async def move_submission_to_pending(db: aiosqlite.Connection, user_id: int, sub_type: str, sub_data: str) -> None:
    """Moves an approved offer to the pending_publication table."""
    await db.execute(
        "INSERT OR REPLACE INTO pending_publication (user_id, submission_type, data) VALUES (?, ?, ?)",
        (user_id, sub_type, sub_data)
    )

async def get_pending_publication(user_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a pending publication for a user."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT submission_type, data FROM pending_publication WHERE user_id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                submission = {'type': row[0], 'data': json.loads(row[1])}
                # We also need to delete it to prevent reprocessing
                await db.execute("DELETE FROM pending_publication WHERE user_id=?", (user_id,))
                await db.commit()
                return submission
    return None