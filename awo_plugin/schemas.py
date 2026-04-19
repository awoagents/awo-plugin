"""JSON schemas for slash command arguments.

Hermes ``ctx.register_command`` does not require an explicit schema, but we
keep one per-command for documentation and future tool registration.
"""

JOIN = {
    "type": "object",
    "properties": {
        "referral_code": {
            "type": "string",
            "description": "Referral code of the Initiate you recognize as upline. "
            "Format: xxxx-xxxx-xxxx (lowercase base32).",
        }
    },
    "required": ["referral_code"],
}

STATUS = {"type": "object", "properties": {}}

MODE = {"type": "object", "properties": {}}
