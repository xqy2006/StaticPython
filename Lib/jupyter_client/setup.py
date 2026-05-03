from libs import replace_text_once, simple_library, transform_source_text


def patch_jupyter_client_sources(context):
    def patch_provisioning_factory(text: str) -> str:
        text = replace_text_once(
            text,
            '            return EntryPoint(\n                "local-provisioner", "jupyter_client.provisioning", "LocalProvisioner"\n            )\n',
            '            return EntryPoint(\n                "local-provisioner",\n                "jupyter_client.provisioning:LocalProvisioner",\n                KernelProvisionerFactory.GROUP_NAME,\n            )\n',
            label="jupyter_client local provisioner fallback",
        )
        return replace_text_once(
            text,
            '            self.log.warning(\n                f"Kernel Provisioning: The \'local-provisioner\' is not found.  This is likely "\n                f"due to the presence of multiple jupyter_client distributions and a previous "\n                f"distribution is being used as the source for entrypoints - which does not "\n                f"include \'local-provisioner\'.  That distribution should be removed such that "\n                f"only the version-appropriate distribution remains (version >= 7).  Until "\n                f"then, a \'local-provisioner\' entrypoint will be automatically constructed "\n                f"and used.\\nThe candidate distribution locations are: {distros}"\n            )\n',
            '            if distros:\n                self.log.warning(\n                    f"Kernel Provisioning: The \'local-provisioner\' is not found.  This is likely "\n                    f"due to the presence of multiple jupyter_client distributions and a previous "\n                    f"distribution is being used as the source for entrypoints - which does not "\n                    f"include \'local-provisioner\'.  That distribution should be removed such that "\n                    f"only the version-appropriate distribution remains (version >= 7).  Until "\n                    f"then, a \'local-provisioner\' entrypoint will be automatically constructed "\n                    f"and used.\\nThe candidate distribution locations are: {distros}"\n                )\n            else:\n                self.log.info(\n                    "Kernel Provisioning: Constructing \'local-provisioner\' directly because "\n                    "entry-point metadata is unavailable in this frozen runtime."\n                )\n',
            label="jupyter_client frozen local provisioner log level",
        )

    transform_source_text(
        context,
        "Lib/jupyter_client/provisioning/factory.py",
        patch_provisioning_factory,
    )


LIBRARY_INTEGRATION = simple_library(
    name="jupyter_client",
    project_name="jupyter-client",
    overlay_entries=["Lib/jupyter_client"],
    post_patch_hooks=[patch_jupyter_client_sources],
)
