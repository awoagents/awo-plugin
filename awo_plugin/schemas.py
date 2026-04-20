"""JSON schemas for slash command arguments.

Hermes ``ctx.register_command`` does not require an explicit schema, but we
keep one per-command for documentation and future tool registration.
"""

STATUS = {"type": "object", "properties": {}}

MODE = {"type": "object", "properties": {}}
