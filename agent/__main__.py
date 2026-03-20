"""Package entry point — allows running the agent as ``python -m agent``."""

import asyncio

from agent.main import main

asyncio.run(main())
