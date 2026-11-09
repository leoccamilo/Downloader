import threading
import unittest
from unittest.mock import patch

import server_downloader as server


class ShutdownTests(unittest.TestCase):
    def test_unload_cannot_stop_an_active_workflow(self):
        lock = threading.Lock()
        lock.acquire()
        with patch.object(server, '_workflow_lock', lock), patch.object(server, '_shutdown_timer', None), patch('threading.Timer') as timer:
            response = server.app.test_client().post('/api/shutdown')
            self.assertEqual(response.get_data(as_text=True), 'BUSY')
            timer.assert_not_called()

    def test_delayed_shutdown_rechecks_for_a_new_workflow(self):
        lock = threading.Lock()
        with patch.object(server, '_workflow_lock', lock), patch.object(server, '_shutdown_timer', None), patch('threading.Timer') as timer, patch.object(server.os, '_exit') as exit_process:
            server.app.test_client().post('/api/shutdown')
            callback = timer.call_args.args[1]
            lock.acquire()
            callback()
            exit_process.assert_not_called()
            lock.release()
            callback()
            exit_process.assert_called_once_with(0)
            self.assertFalse(lock.locked())


if __name__ == '__main__':
    unittest.main()
