from libs import replace_text_once, simple_library, transform_source_text


def patch_portalocker_sources(context):
    def patch_windows_locker(text):
        portalocker_4_optional_win32 = (
            "        _win32_locker: Win32Locker | None\n",
            "                self._win32_locker = Win32Locker()\n"
            "            except ImportError:\n",
            "                if win32_locker is None:\n"
            "                    raise ImportError(\n",
        )
        if all(anchor in text for anchor in portalocker_4_optional_win32):
            # portalocker 4.0.0 made pywin32 an optional extra upstream.  Its
            # exclusive-lock path now remains usable when Win32Locker cannot
            # be created, which is the behavior this integration used to add.
            return text
        if "class MsvcrtLocker(BaseLocker):" not in text:
            if "Win32Locker" in text and "msvcrt" in text:
                raise RuntimeError("portalocker MsvcrtLocker lazy Win32 setup anchor not found")
            return text
        text = replace_text_once(
            text,
            "    class MsvcrtLocker(BaseLocker):\n"
            "        _win32_locker: Win32Locker\n"
            "        _msvcrt_lock_length: int = 0x10000\n"
            "\n"
            "        def __init__(self) -> None:\n"
            "            self._win32_locker = Win32Locker()\n"
            "            try:\n",
            "    class MsvcrtLocker(BaseLocker):\n"
            "        _win32_locker: Optional[Win32Locker]\n"
            "        _msvcrt_lock_length: int = 0x10000\n"
            "\n"
            "        def __init__(self) -> None:\n"
            "            self._win32_locker = None\n"
            "            try:\n",
            label="portalocker MsvcrtLocker lazy Win32 setup",
        )
        text = replace_text_once(
            text,
            "                self._win32_locker.lock(file_obj, win32_api_flags)\n"
            "                return\n",
            "                self._get_win32_locker().lock(file_obj, win32_api_flags)\n"
            "                return\n",
            label="portalocker shared-lock Win32 fallback",
        )
        text = replace_text_once(
            text,
            "        def lock(self, file_obj: types.FileArgument, flags: LockFlags) -> None:\n"
            "            import msvcrt\n",
            "        def _get_win32_locker(self) -> Win32Locker:\n"
            "            if self._win32_locker is None:\n"
            "                self._win32_locker = Win32Locker()\n"
            "            return self._win32_locker\n"
            "\n"
            "        def lock(self, file_obj: types.FileArgument, flags: LockFlags) -> None:\n"
            "            import msvcrt\n",
            label="portalocker lazy Win32 accessor",
        )
        return replace_text_once(
            text,
            "                        self._win32_locker.unlock(\n"
            "                            file_obj\n"
            "                        )  # win32_locker handles its own seeking\n",
            "                        self._get_win32_locker().unlock(\n"
            "                            file_obj\n"
            "                        )  # win32_locker handles its own seeking\n",
            label="portalocker unlock Win32 fallback",
        )

    transform_source_text(context, "Lib/portalocker/portalocker.py", patch_windows_locker)


LIBRARY_INTEGRATION = simple_library(
    name="portalocker",
    overlay_entries=["Lib/portalocker"],
    post_patch_hooks=[patch_portalocker_sources],
)
