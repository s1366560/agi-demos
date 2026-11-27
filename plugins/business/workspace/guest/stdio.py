"""Child process for one signed business command."""

from plugins.business.guest_runtime.serve import main
from plugins.business.workspace.guest.dispatch import OPERATIONS

if __name__ == "__main__":
    main(OPERATIONS)
