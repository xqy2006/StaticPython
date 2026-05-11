import re

from libs import replace_function_block_once, replace_regex_once, simple_library, transform_first_existing_source_text


def patch_jupyter_client_sources(context):
    def patch_provisioning_factory(text: str) -> str:
        if "local-provisioner" not in text and "KernelProvisionerFactory" not in text:
            return text
        if "def _get_provisioner(" in text:
            return replace_function_block_once(
                text,
                "_get_provisioner",
                "def _get_provisioner(self, name: str) -> EntryPoint:\n"
                "    \"\"\"Wrapper around entrypoints.get_single() - primarily to facilitate testing.\"\"\"\n"
                "    try:\n"
                "        ep = get_single(KernelProvisionerFactory.GROUP_NAME, name)\n"
                "    except NoSuchEntryPoint:\n"
                "        if name == 'local-provisioner':\n"
                "            distros = glob.glob(f\"{path.dirname(path.dirname(__file__))}-*\")\n"
                "            if distros:\n"
                "                self.log.warning(\n"
                "                    f\"Kernel Provisioning: The 'local-provisioner' is not found.  This is likely \"\n"
                "                    f\"due to the presence of multiple jupyter_client distributions and a previous \"\n"
                "                    f\"distribution is being used as the source for entrypoints - which does not \"\n"
                "                    f\"include 'local-provisioner'.  That distribution should be removed such that \"\n"
                "                    f\"only the version-appropriate distribution remains (version >= 7).  Until \"\n"
                "                    f\"then, a 'local-provisioner' entrypoint will be automatically constructed \"\n"
                "                    f\"and used.\\nThe candidate distribution locations are: {distros}\"\n"
                "                )\n"
                "            else:\n"
                "                self.log.info(\n"
                "                    \"Kernel Provisioning: Constructing 'local-provisioner' directly because \"\n"
                "                    \"entry-point metadata is unavailable in this frozen runtime.\"\n"
                "                )\n"
                "            ep = EntryPoint(\n"
                "                'local-provisioner', 'jupyter_client.provisioning', 'LocalProvisioner'\n"
                "            )\n"
                "        else:\n"
                "            raise\n"
                "    return ep\n",
                label="jupyter_client local provisioner fallback",
            )
        return text

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
