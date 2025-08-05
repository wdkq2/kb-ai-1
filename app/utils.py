"""Utility functions for loading environment variables.

In some container environments `python-dotenv` cannot be installed. This
module provides a very small substitute for loading key=value pairs from a
.env file into the process environment. Only the first assignment to a
variable wins (existing environment variables are not overwritten).
"""
import os
from typing import Optional


def load_env(path: Optional[str] = None) -> None:
    """Load environment variables from a .env file.

    Parameters
    ----------
    path : str | None, optional
        Path to the .env file. If None, `.env` in the current working
        directory is used.

    This function silently does nothing if the file does not exist.
    """
    if path is None:
        path = '.env'
    if not os.path.isfile(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, value = line.split('=', 1)
                # do not override existing environment variables
                if key not in os.environ:
                    os.environ[key] = value
    except Exception:
        # ignore any read/parse errors
        pass