import re

from libs import replace_regex_once, simple_library, transform_first_existing_source_text


def patch_jupyter_client_sources(context):
    def patch_provisioning_factory(text: str) -> str:
        if "local-provisioner" not in text and "KernelProvisionerFactory" not in text:
            return text
        entrypoint_pattern = re.compile(
            r"(?ms)(\s+return EntryPoint\()\s*['\"]local-provisioner['\"],\s*['\"]jupyter_client\.provisioning['\"],\s*['\"]LocalProvisioner['\"]\s*(\))"
        )
        if '"jupyter_client.provisioning:LocalProvisioner"' not in text:
            def entrypoint_repl(match: re.Match[str]) -> str:
                prefix = match.group(1)
                suffix = match.group(2)
                return (
                    f"{prefix}\n"
                    '                "local-provisioner",\n'
                    '                "jupyter_client.provisioning:LocalProvisioner",\n'
                    "                KernelProvisionerFactory.GROUP_NAME,\n"
                    f"            {suffix}"
                )

            updated, count = entrypoint_pattern.subn(entrypoint_repl, text, count=1)
            if count != 1:
                raise RuntimeError("expected regex not found in jupyter_client local provisioner fallback")
            text = updated
        pattern = re.compile(
            r"(?ms)(\s+)self\.log\.warning\(\n(\s+)f\"Kernel Provisioning: The 'local-provisioner' is not found\..*?\n\1\)\n"
        )
        if "entry-point metadata is unavailable in this frozen runtime." in text:
            return text

        def repl(match: re.Match[str]) -> str:
            indent = match.group(1)
            inner_indent = match.group(2)
            return (
                f"{indent}if distros:\n"
                f"{indent}    self.log.warning(\n"
                f'{inner_indent}f"Kernel Provisioning: The \'local-provisioner\' is not found.  This is likely "\n'
                f'{inner_indent}f"due to the presence of multiple jupyter_client distributions and a previous "\n'
                f'{inner_indent}f"distribution is being used as the source for entrypoints - which does not "\n'
                f'{inner_indent}f"include \'local-provisioner\'.  That distribution should be removed such that "\n'
                f'{inner_indent}f"only the version-appropriate distribution remains (version >= 7).  Until "\n'
                f'{inner_indent}f"then, a \'local-provisioner\' entrypoint will be automatically constructed "\n'
                f'{inner_indent}f"and used.\\nThe candidate distribution locations are: {{distros}}"\n'
                f"{indent}    )\n"
                f"{indent}else:\n"
                f"{indent}    self.log.info(\n"
                f'{indent}        "Kernel Provisioning: Constructing \'local-provisioner\' directly because "\n'
                f'{indent}        "entry-point metadata is unavailable in this frozen runtime."\n'
                f"{indent}    )\n"
            )

        updated, count = pattern.subn(repl, text, count=1)
        if count != 1:
            raise RuntimeError("expected regex not found in jupyter_client frozen local provisioner log level")
        return updated

    transform_first_existing_source_text(
        context,
        [
            "Lib/jupyter_client/provisioning/factory.py",
            "Lib/jupyter_client/kernelspec.py",
        ],
        patch_provisioning_factory,
        allow_all_missing=True,
    )


LIBRARY_INTEGRATION = simple_library(
    name="jupyter_client",
    project_name="jupyter-client",
    overlay_entries=["Lib/jupyter_client"],
    post_patch_hooks=[patch_jupyter_client_sources],
)
