# Command generation

`nsc/builder/` walks the parsed schema and produces a `CommandModel`.

## The shape

```python
CommandModel(info_title, info_version, schema_hash, tags: dict[str, Tag])
├── tags: dict[str, Tag]
│   └── Tag(name, description?, resources: dict[str, Resource])
│       └── Resource(name, list_op?, get_op?, create_op?, update_op?, replace_op?,
│                    delete_op?, custom_actions: list[Operation])
└── Operation(operation_id, http_method, path, summary?, description?,
              parameters, request_body?, default_columns?)
```

Pure Pydantic. JSON-serializable. Cached to disk.

## Verb derivation

| HTTP method + path shape | Verb |
|---|---|
| `GET /things/` | `list` |
| `GET /things/{id}/` | `get` |
| `POST /things/` | `create` |
| `PATCH /things/{id}/` | `update` |
| `PUT /things/{id}/` | `replace` |
| `DELETE /things/{id}/` | `delete` |

Custom action endpoints (e.g., `/api/ipam/prefixes/{id}/available-ips/`)
become verbs derived from `operationId`, kebab-cased, with the resource prefix
stripped:

`ipam_prefixes_available_ips_list` → `nsc ipam prefixes available-ips <id>`

## Bulk endpoints

When the schema declares an array request body for the same path as the
single-record `create` (NetBox does this for bulk-create on most resources),
the builder marks the operation as bulk-capable. The CLI uses the bulk variant
when input is a list; otherwise it loops.

## Sub-resources

NetBox's sub-resource relationships (a device's interfaces, a prefix's
addresses) are query-param filters in the schema, not nested paths. So they
surface as flags on top-level resources, not nested commands:

```sh
nsc dcim interfaces list --device-id 42       # not "nsc dcim devices interfaces 42"
```

## Plugin endpoints

Plugins register their tags and paths the same way core does. The builder
treats them identically — no per-plugin code path.
