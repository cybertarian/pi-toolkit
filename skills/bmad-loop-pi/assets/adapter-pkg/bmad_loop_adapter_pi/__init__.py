"""bmad-loop adapter-kind package for the pi coding agent.

Installed alongside bmad-loop into the same environment
(``uv tool install bmad-loop --with bmad-loop-adapter-pi``). Importing this
package registers the ``pi`` adapter kind with bmad-loop's live registry via
the ``bmad_loop.adapters`` entry point; a selectable ``pi`` profile is added
separately (project overlay ``.bmad-loop/profiles/pi.toml``, or a
``bmad_loop.profiles`` entry point if this package ships one).

A failure to import or load this module must never break bmad-loop: the
registry records the failure and selection proceeds without the kind
(``bmad-loop adapters`` names it).
"""

from bmad_loop.adapters.registry import AdapterBuilder, register_adapter


def _load() -> AdapterBuilder:
    # Lazy import: the kind's classes (and anything they pull in) load only
    # when a run actually selects a pi profile, never from validate/adapters
    # listing.
    from .pi_adapter import PiAdapter, PiDevAdapter

    return AdapterBuilder(
        plain=PiAdapter,
        dev=PiDevAdapter,
        construct_error=(),
    )


register_adapter("pi", needs_mux=False, load=_load)

__all__ = ["_load"]
