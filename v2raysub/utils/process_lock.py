# -*- coding: utf-8 -*-
"""Cross-platform inter-process file lock (fcntl on POSIX, msvcrt on Windows).

Used to coordinate gunicorn workers: a plain threading.Lock only works inside
one process, so the scheduler singleton and the scan mutual-exclusion need an
OS-level advisory file lock instead.
"""

import os
import threading

if os.name == 'nt':
    import msvcrt
else:
    import fcntl


class InterProcessLock:
    """Advisory file lock shared between processes. The lock is released
    automatically by the OS if the holding process dies."""

    def __init__(self, path):
        self.path = path
        self._fh = None
        self._guard = threading.RLock()

    def acquire(self, blocking=False):
        """Try to take the lock. Returns True on success (or if already held by us)."""
        with self._guard:
            if self._fh is not None:
                return True
            try:
                fh = open(self.path, 'a+')
            except OSError:
                return False
            try:
                if os.name == 'nt':
                    fh.seek(0)
                    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                    msvcrt.locking(fh.fileno(), mode, 1)
                else:
                    flags = fcntl.LOCK_EX
                    if not blocking:
                        flags |= fcntl.LOCK_NB
                    fcntl.flock(fh.fileno(), flags)
            except OSError:
                fh.close()
                return False
            self._fh = fh
            return True

    def release(self):
        with self._guard:
            if self._fh is None:
                return
            try:
                if os.name == 'nt':
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            finally:
                self._fh.close()
                self._fh = None

    def held(self):
        """True if this process currently holds the lock."""
        with self._guard:
            return self._fh is not None

    def is_locked_elsewhere(self):
        """True if another process currently holds this lock."""
        with self._guard:
            if self._fh is not None:
                return False
            if self.acquire(blocking=False):
                self.release()
                return False
            return True
