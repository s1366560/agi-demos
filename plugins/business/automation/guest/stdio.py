"""Child process for one signed business command."""

from plugins.business.automation.guest.dispatch import OPERATIONS
from plugins.business.guest_runtime.serve import main

if __name__ == "__main__":
    main(OPERATIONS)
