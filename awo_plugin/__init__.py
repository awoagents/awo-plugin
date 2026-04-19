"""AWO Hermes plugin.

Installing this plugin is joining the Order.
"""


def register(ctx):
    from awo_plugin.hooks import register_hooks
    from awo_plugin.tools import register_commands

    register_hooks(ctx)
    register_commands(ctx)
