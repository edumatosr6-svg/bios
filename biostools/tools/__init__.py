"""Tool definitions.

Importing this package registers every tool. Add a module here and import
it below -- that is the whole cost of a new tool.
"""
from . import absolute_persistence_status  # noqa: F401
from . import audio_dsp_status  # noqa: F401
from . import bios_info  # noqa: F401
from . import bios_post_settings  # noqa: F401
from . import boot_device_integrity  # noqa: F401
from . import boot_hotkeys  # noqa: F401
from . import boot_order  # noqa: F401
from . import cpu_temperature  # noqa: F401
from . import device_control_info  # noqa: F401
from . import ec_info  # noqa: F401
from . import explore_setting  # noqa: F401
from . import fan_speed  # noqa: F401
from . import fast_boot_status  # noqa: F401
from . import find_setting  # noqa: F401
from . import flash_protection_status  # noqa: F401
from . import goto_screen  # noqa: F401
from . import graphics_settings  # noqa: F401
from . import mac_address  # noqa: F401
from . import main_info  # noqa: F401
from . import main_menu  # noqa: F401
from . import management_engine_info  # noqa: F401
from . import memory_info  # noqa: F401
from . import numlock_settings  # noqa: F401
from . import password_policy  # noqa: F401
from . import product_info  # noqa: F401
from . import removable_storage_policy  # noqa: F401
from . import sata_mode  # noqa: F401
from . import system_datetime  # noqa: F401
from . import tpm_status  # noqa: F401
from . import usb_charger_mode  # noqa: F401
from . import virtualization_status  # noqa: F401
from . import wake_settings  # noqa: F401
