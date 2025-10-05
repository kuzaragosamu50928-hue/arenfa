import os
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web

# We need to import setup_routes to build the app, which in turn imports the handlers.
# Patching needs to happen on the objects as they are seen by the handlers module.
from src.web.routes import setup_routes

# Define mock objects for bot functions to return
mock_file_info = MagicMock()
mock_file_info.file_path = "some/mock/path"
mock_file_content = b"test_image_content"

# Create a mock bot object. This will be used to replace the real bot.
# Its async methods need to be AsyncMocks.
mock_hunter_bot = MagicMock()
mock_hunter_bot.get_file = AsyncMock(return_value=mock_file_info)
mock_hunter_bot.download_file = AsyncMock(return_value=mock_file_content)

class TestGetImageHandler(AioHTTPTestCase):
    """Tests the get_image handler with proper, isolated mocking."""

    async def get_application(self):
        """Creates the aiohttp test application."""
        app = web.Application()
        # The handlers are registered here. The patches will already be active
        # when the test methods run and call the handlers.
        setup_routes(app)
        return app

    def setUp(self):
        """Set up mocks before each test method."""
        super().setUp()

        # Reset mocks to ensure test isolation
        mock_hunter_bot.get_file.reset_mock()
        mock_hunter_bot.download_file.reset_mock()

        # Patch the bot directly in the handlers module where it's used.
        # This is the crucial fix.
        self.hunter_patcher = patch('src.web.handlers.hunter_bot', mock_hunter_bot)
        self.hunter_patcher.start()

        # Patch the database connection within the handlers module.
        self.db_patcher = patch('src.web.handlers.aiosqlite.connect')
        self.mock_db_connect = self.db_patcher.start()

        # Configure the mock database to return a mock connection and cursor.
        self.mock_db_conn = AsyncMock()
        self.mock_db_cursor = AsyncMock()
        self.mock_db_connect.return_value.__aenter__.return_value = self.mock_db_conn
        self.mock_db_conn.execute.return_value = self.mock_db_cursor

    def tearDown(self):
        """Clean up and stop all patchers after each test."""
        super().tearDown()
        patch.stopall() # this will stop hunter_patcher and db_patcher

    @unittest_run_loop
    async def test_get_image_for_public_listing(self):
        """Test: Image for a public listing should be returned successfully."""
        public_file_id = "file_id_public_123"

        # Simulate that the database found a public listing with this file_id.
        self.mock_db_cursor.fetchone.return_value = (1,)

        resp = await self.client.request("GET", f"/api/image/{public_file_id}")

        self.assertEqual(resp.status, 200)
        content = await resp.read()
        self.assertEqual(content, mock_file_content)

        # Verify that the database was checked.
        self.mock_db_conn.execute.assert_called_once_with(
            "SELECT 1 FROM listings WHERE data LIKE ?", (f'%"{public_file_id}"%',)
        )
        # Verify that the bot was called to download the file.
        mock_hunter_bot.get_file.assert_called_once_with(public_file_id)
        mock_hunter_bot.download_file.assert_called_once_with(mock_file_info.file_path)

    @unittest_run_loop
    async def test_get_image_for_private_submission(self):
        """Test: Image for a private/non-existent listing should be rejected."""
        private_file_id = "file_id_private_456"

        # Simulate that the database did NOT find any public listing.
        self.mock_db_cursor.fetchone.return_value = None

        resp = await self.client.request("GET", f"/api/image/{private_file_id}")

        self.assertEqual(resp.status, 404)

        # Verify that the database was checked.
        self.mock_db_conn.execute.assert_called_once_with(
            "SELECT 1 FROM listings WHERE data LIKE ?", (f'%"{private_file_id}"%',)
        )
        # Verify that the bot was NOT called, preventing the data leak.
        mock_hunter_bot.get_file.assert_not_called()
        mock_hunter_bot.download_file.assert_not_called()

if __name__ == "__main__":
    os.environ['MODERATOR_BOT_TOKEN'] = 'dummy_token'
    os.environ['HUNTER_BOT_TOKEN'] = 'dummy_token'
    os.environ['CHANNEL_ID'] = 'dummy_channel'
    os.environ['ADMIN_ID'] = 'dummy_admin'
    unittest.main()