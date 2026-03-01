"""Database repository layer for the AI Agent Crypto Trading Platform.

Each repository class wraps a specific ORM model and provides typed async
CRUD methods.  All DB access goes through these classes — never call
``session.execute`` directly from service or route code.
"""
