# Loaded by netbox-docker from /etc/netbox/config/. Values mirror the DB_*
# env vars in tests/e2e/docker-compose.yml.
from netbox_branching.utilities import DynamicSchemaDict

PLUGINS = ["netbox_branching"]

DATABASES = DynamicSchemaDict(
    {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "netbox",
            "USER": "netbox",
            "PASSWORD": "netbox",
            "HOST": "postgres",
            "PORT": "",
            "CONN_MAX_AGE": 300,
        }
    }
)

DATABASE_ROUTERS = ["netbox_branching.database.BranchAwareRouter"]
