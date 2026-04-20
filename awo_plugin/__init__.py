"""AWO Hermes plugin.

Installing this plugin is joining the Order.
"""


def register(ctx):
    from awo_plugin import state as state_mod
    from awo_plugin.hooks import ensure_initiate, register_hooks
    from awo_plugin.tools import register_commands

    register_hooks(ctx)
    register_commands(ctx)

    # Proactive init — don't wait for on_session_start. If the gateway
    # doesn't restart after pip install, register(ctx) is the earliest
    # point we have ctx and can persist a fingerprint so /awo_init,
    # /awo_status, and registry submission work from turn one.
    try:
        st = state_mod.load()
        if not st.get("fingerprint"):
            st = ensure_initiate(ctx, st)
            state_mod.save(st)
    except Exception:
        # Any failure is swallowed; on_session_start will retry.
        pass
