from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="faker",
    project_name="Faker",
    overlay_entries=["Lib/faker"],
    runtime_resource_paths=[
        "Lib/faker/providers",
    ],
    verification_steps=[
        inline_verification_step(
            "faker-smoke",
            """
from faker import Faker

Faker.seed(12345)
fake = Faker("en_US")
name = fake.name()
email = fake.email()
profile = fake.simple_profile()
assert isinstance(name, str) and " " in name
assert "@" in email
assert {"username", "name", "sex", "address", "mail", "birthdate"} <= set(profile)
""",
        )
    ],
)
