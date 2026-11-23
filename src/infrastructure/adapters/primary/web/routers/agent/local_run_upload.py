"""Full API registration of the shared device run protocol."""

from src.host.transport.local_run_upload import (
    RegisterLocalRunBody as RegisterLocalRunBody,
    get_local_run_events as get_local_run_events,
    patch_local_run_terminal as patch_local_run_terminal,
    post_local_run as post_local_run,
    post_local_run_events as post_local_run_events,
    post_local_run_stop as post_local_run_stop,
    router as router,
)
