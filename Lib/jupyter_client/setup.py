from libs import replace_function_block_once, simple_library, transform_source_text


def patch_jupyter_client_sources(context):
    def patch_provisioning_factory(text: str) -> str:
        return replace_function_block_once(
            text,
            "_get_provisioner",
            """    def _get_provisioner(self, name: str) -> EntryPoint:
        \"\"\"Wrapper around entry_points (to fetch a single provisioner) - primarily to facilitate testing.\"\"\"
        try:
            eps = entry_points(group=KernelProvisionerFactory.GROUP_NAME, name=name)
        except TypeError:
            try:
                discovered = entry_points(group=KernelProvisionerFactory.GROUP_NAME)
            except TypeError:
                discovered = entry_points()
            if hasattr(discovered, "select"):
                eps = list(discovered.select(group=KernelProvisionerFactory.GROUP_NAME, name=name))
            elif isinstance(discovered, dict):
                eps = [ep for ep in discovered.get(KernelProvisionerFactory.GROUP_NAME, []) if ep.name == name]
            else:
                eps = [
                    ep for ep in discovered
                    if getattr(ep, "group", None) == KernelProvisionerFactory.GROUP_NAME and ep.name == name
                ]
        if eps:
            return list(eps)[0]

        if name == 'local-provisioner':
            distros = glob.glob(f"{path.dirname(path.dirname(__file__))}-*")
            if distros:
                self.log.warning(
                    f"Kernel Provisioning: The 'local-provisioner' is not found.  This is likely "
                    f"due to the presence of multiple jupyter_client distributions and a previous "
                    f"distribution is being used as the source for entrypoints - which does not "
                    f"include 'local-provisioner'.  That distribution should be removed such that "
                    f"only the version-appropriate distribution remains (version >= 7).  Until "
                    f"then, a 'local-provisioner' entrypoint will be automatically constructed "
                    f"and used.\\nThe candidate distribution locations are: {distros}"
                )
            else:
                self.log.info(
                    "Kernel Provisioning: Constructing 'local-provisioner' directly because "
                    "entry-point metadata is unavailable in this frozen runtime."
                )
            try:
                return EntryPoint(
                    'local-provisioner',
                    'jupyter_client.provisioning:LocalProvisioner',
                    KernelProvisionerFactory.GROUP_NAME,
                )
            except TypeError:
                return EntryPoint(
                    'local-provisioner', 'jupyter_client.provisioning', 'LocalProvisioner'
                )

        raise ModuleNotFoundError(name)
""",
            label="jupyter_client local provisioner fallback",
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
