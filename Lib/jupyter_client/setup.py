from libs import replace_regex_once, simple_library, transform_first_existing_source_text


def patch_jupyter_client_sources(context):
    def patch_provisioning_factory(text: str) -> str:
        if "local-provisioner" not in text and "KernelProvisionerFactory" not in text:
            return text
        text = replace_regex_once(
            text,
            r"(?ms)(\s+return EntryPoint\()\s*['\"]local-provisioner['\"],\s*['\"]jupyter_client\.provisioning['\"],\s*['\"]LocalProvisioner['\"]\s*(\))",
            r'\1'
            '\n                "local-provisioner",'
            '\n                "jupyter_client.provisioning:LocalProvisioner",'
            '\n                KernelProvisionerFactory.GROUP_NAME,'
            '\n            \2',
            label="jupyter_client local provisioner fallback",
        )
        return replace_regex_once(
            text,
            r"(?ms)(\s+)self\.log\.warning\(\n(\s+)f\"Kernel Provisioning: The 'local-provisioner' is not found\..*?\n\1\)\n",
            r'\1if distros:'
            r'\n\1    self.log.warning('
            r'\n\2f"Kernel Provisioning: The ''local-provisioner'' is not found.  This is likely "'
            r'\n\2f"due to the presence of multiple jupyter_client distributions and a previous "'
            r'\n\2f"distribution is being used as the source for entrypoints - which does not "'
            r'\n\2f"include ''local-provisioner''.  That distribution should be removed such that "'
            r'\n\2f"only the version-appropriate distribution remains (version >= 7).  Until "'
            r'\n\2f"then, a ''local-provisioner'' entrypoint will be automatically constructed "'
            r'\n\2f"and used.\nThe candidate distribution locations are: {distros}"'
            r'\n\1    )'
            r'\n\1else:'
            r'\n\1    self.log.info('
            r'\n\1        "Kernel Provisioning: Constructing ''local-provisioner'' directly because "'
            r'\n\1        "entry-point metadata is unavailable in this frozen runtime."'
            r'\n\1    )'
            r'\n',
            label="jupyter_client frozen local provisioner log level",
        )

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
