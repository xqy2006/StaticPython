from libs import simple_library


LIBRARY_INTEGRATION = simple_library(
    name='win32_setctime',
    overlay_entries=['Lib/win32_setctime'],
)
