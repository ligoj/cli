[[_TOC_]]

# Description

Ligoj CLI makes REST calls to a remote Ligoj instance, with parameters and error handling.

# Requirements

- Python 3.11+
- Connectivity and API keys to the target endpoints: `Ligoj` (required) and, for `bootstrap` actions, `Nexus`, `Jenkins`, `SonarQube`
- Valid [credentials](#credentials)

# Installation

Ligoj CLI is published on [PyPI](https://pypi.org/project/ligoj-cli/) as `ligoj-cli` and provides the `ligoj` command.

Install it as an isolated tool with [`uv`](https://docs.astral.sh/uv/) (recommended):

```bash
uv tool install ligoj-cli
ligoj --version
```

Alternatively, use `pipx` or `pip`:

```bash
pipx install ligoj-cli
# or
pip install ligoj-cli
```

To try the latest pre-release published on [TestPyPI](https://test.pypi.org/project/ligoj-cli/):

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ ligoj-cli
```

For local development from a checkout, see [Development](#development).


# Configuration

## Credentials

Ligoj credentials are based on user/password or user/API Key.

Populate the [configuration files](#configuration-files) with the API key created here [#/api/token ("?" > "Api" > "Token")](http://localhost:8080/ligoj/#/api/token)

You can also:
- use the [session login](#login-with-password) command to get a temporary session
- use the [token](#token) command to create durable API keys

For standard actions, only `LIGOJ_ENDPOINT` is required and can be set either in the [configuration files](#configuration-files), as an environment variable, or as a CLI option.

For `bootstrap` actions, more endpoints and credentials may be required in the [configuration files](#configuration-files).

Sample usage:

```bash
ligoj \
--api-user="ligoj-admin" \
--api-key="..." \
--endpoint="http://localhost:8080/ligoj" \
--version
```

# Commands

## Settings

Options are sourced in the following order of priority, from highest to lowest:

1. Command line options – Overrides settings in any other location, such as the `--output` and `--profile` parameters.
2. Environment variables – You can store values in your system's environment variables.
3. Session file – `default` section or given profile name. The session file is located at `~/.ligoj/sessions` on Linux or macOS and holds:
  - Session cookies set with the [`login`](#login-with-password) command.
  - API keys set with the [`login`](#login-with-api-key) command.
4. Credentials file – `default` section or given profile name. The credentials file is located at `~/.ligoj/credentials` on Linux or macOS.
5. Configuration file – `default` section or given profile name. The config file is located at `~/.ligoj/config` on Linux or macOS. Alternative file `~/.ligoj/cli-config` is supported.


### Configuration files

Sections in these `.ini` files correspond to profile names. The default profile name is `default` and is used when no `--profile` option and no `LIGOJ_PROFILE` are provided.

In the file `~/.ligoj/config`, default configurations can be specified. No secrets are sourced from this file.

```ini
[default]
output = "json"
log_level = "DEBUG"
endpoint=http://localhost:8080/ligoj
jenkins_endpoint=http://localhost:8086
sonar_endpoint=http://localhost:9000/

[some]
output = "json"
```

Read-only secrets are stored in the `~/.ligoj/credentials` file. 

Temporary secrets (stored from the [`session`](#session) command) are stored in the `~/.ligoj/sessions` file. 

While `~/.ligoj/credentials` can contain configuration settings, secrets are only sourced from the `~/.ligoj/credentials` and `~/.ligoj/sessions` files.

Sample credential file:
```ini
[default]
api_user = ligoj-user1
api_key = secret
jenkins_api_user = admin
jenkins_api_token = secret
sonar_api_token = secret
```

*Note* Leading spaces are ignored, and enclosing `'` and `"` are removed. Empty strings are ignored.

## Generic options

The generic options are available to all actions.

### Output mode

Determines the output mode of the command. Use the `--output` option. The following modes are available:

- `json` : JSON format
- `text` : Text format

This option can also be specified in [configuration files](#configuration-files) as `output` or in environment variable `LIGOJ_OUTPUT`

```bash
ligoj --output json --version
ligoj --version
```

```json
{"version": "3.3.1-SNAPSHOT"}
```

```bash
ligoj --output text --version
```

```txt
3.3.1-SNAPSHOT
```

### Log level

To configure the verbosity, use the `--log-level` option. The following levels are available:

- `TRACE` level displays the in/out data. `--verbose` and `--trace` are shortcuts for this level.
- `DEBUG` level displays the internal API calls `--debug` is a shortcut for this level.
- `INFO` level displays the actions
- `WARN` level displays the unexpected behaviors
- `ERROR` level displays only fatal errors

This option can also be specified in [configuration files](#configuration-files) as `log-level` or in environment variable `LIGOJ_LOG_LEVEL`

```bash
ligoj --log-level INFO ....
ligoj --verbose ....
ligoj --trace ....
```

If you want to pipe JSON result to `jq`, use `--output json` and `--log-level ERROR` options.


### Insecure server connections

To allow insecure server connections when using SSL, use the `--insecure` option. This option can also be specified in [configuration files](#configuration-files) as `insecure` or in environment variable `LIGOJ_INSECURE`

```bash
ligoj --insecure ....
ligoj --k ....
```

### API user

Ligoj API user name. Use the `--api-user` option. This option can also be specified in [configuration files](#configuration-files) as `api-user` or in environment variable `LIGOJ_API_USER`. By default is `ligoj-admin`.

```bash
ligoj --api-user ligoj-admin ....
```

### API key

Provide an API key, which can be created here [#/api/token ("?" > "Api" > "Token")](https://localhost:8080/ligoj/#/api/token). Use the `--api-key` option. This option can also be specified in [configuration files](#configuration-files) as `api-key` or in environment variable `LIGOJ_API_KEY`

```bash
ligoj --api-key secret ....
```


### API run as user

Ligoj API user name for impersonation. Use the `--api-run-as-user` option. This option can also be specified in [configuration files](#configuration-files) as `api-run-as-user` or in environment variable `LIGOJ_API_RUN_AS_USER`.

Constraints are:
- After the authentication succeeds with [--api-key](#api-key) and [--api-user](#api-user)
- The current user must have `POST /system.user` authorization
- `--api-run-as-user` must exist
- The actions are executed in the name of `--api-run-as-user` and without needing the related credentials.

This option can also be specified in [configuration files](#configuration-files) as `api-run-as-user` or in environment variable `LIGOJ_API_RUN_AS_USER`.

```bash
ligoj --api-run-as-user ligoj-user ....
```


### API local roles

Restrict the computed roles to the local roles of the authenticated user. No plugin roles are involved.
This flag makes the authentication independent of the configured plugins (e.g., availability, misconfiguration, etc.).

Since this flag reduces the set of available roles, there is no restriction on the usage.

This option can also be specified in [configuration files](#configuration-files) as `api-local-roles` or in environment variable `LIGOJ_API_LOCAL_ROLES`.

```bash
ligoj --api-local-roles session get
```


### Profile

Ligoj profile name to read from [configuration files](#configuration-files),  `credentials`, `config`, and `sessions`. Use the `--profile` option. This option can also be specified with environment variable `LIGOJ_PROFILE`. The default is `default`.

```bash
ligoj --profile some ....
```

### From

JSON content to load. Use the `--from` option. The following forms are available:

- Path to a local JSON file
- Remote HTTP URL
- Inline JSON string

After the content has been retrieved, it is interpolated with [Jinja](https://pypi.org/project/Jinja2/) with current project (`project`) and environment variables (`env`) as context:
- For example:
  - `{{ project.id }}` is replaced by the project identifier. 
  - `{{ env.ENV_VAR }}` is replaced by the `ENV_VAR` environment variable value. 
  - `$${_not_existing_property_in_context_}` is replaced by an empty string.
- `null` values are considered as empty string
- The context depends on the current action. Usually, all given parameters are added to the context.
- The context is completed with environment variables.
- Surrounding spaces inside `{{..}}` are ignored

### No color

Disable colors in messages. Use the `--no-color` option. This option can also be specified in [configuration files](#configuration-files) as `no-color` or in environment variable `LIGOJ_NO_COLOR`

```bash
ligoj --no-color ....
```

### Fail on hook error

Fail (exit code 1) when any hook returns a failure status (`X-Ligoj-Hook-*=FAILED`). See [hooks](https://github.com/ligoj/ligoj/blob/master/DOC.md#hook) for more details. Use the `--fail-on-hook-error` option. This option can also be specified in [configuration files](#configuration-files) as `fail-on-hook-error` or in environment variable `LIGOJ_FAIL_ON_HOOK_ERROR`

```bash
ligoj --fail-on-hook-error ....
```

Fail (exit code 1) when any hook returns a failure status (`X-Ligoj-Hook-*=FAILED`). See [hooks](https://github.com/ligoj/ligoj/blob/master/DOC.md#hook) for more details.

Hooks status and message are displayed with `DEBUG` log level:
```log
[DEBUG] [ligoj] Hook 'audit_role_change' status: SUCCEED
[DEBUG] [ligoj] Hook 'audit_role_change' status: FAILED: Message for user
```

## Session

Session operations with credentials and profile management.

### Login with password

Verify the provided user and password and save the returned session cookie into the `~/.ligoj/sessions` file for further API call without providing credentials.

*Note* Secrets like `api-user` and `password` are sourced from the CLI options, sessions and credential files, not from the configuration one.


```bash
ligoj --api-user "ligoj-admin" --profile default session login --password secret
ligoj --api-user "ligoj-admin" login session --password secret
```

Completed `~/.ligoj/sessions` file:

```ini
[default]
session = session_secret_value.node0
api_user = ligoj-admin
```

### Login with api key

Verify the provided user and API key and save the provided API user and API keys into the `~/.ligoj/sessions` file for further API call without providing credentials.

*Note* Secrets like `api-user` and `password` are sourced from the CLI options, sessions and credential files, not from the configuration one.

```bash
ligoj --api-user "ligoj-admin" --api-key "__api_key__" session login
```

### Get session

Return user session details

```bash
ligoj session get
```

```json
{
  "applicationSettings": {
    "buildNumber": "", "buildTimestamp": "", "buildVersion": "3.3.1-SNAPSHOT", 
    "digestVersion": "rRXmeWPgn+...==",
    "plugins": ["feature:welcome:data-rbac"]
  }, 
  "userSettings": {"security-agreement": "1"}, 
  "uiAuthorizations": ["^id/container/group.*", "^id/user.*", "^id/delegate.*", "^message.*", "^id$", "^home.*", "^id/container/company.*", "^api.*", "^id/home.*", ".*"], 
  "apiAuthorizations": [{"pattern": ".*", "method": "DELETE"}], "roles": ["ADMIN", "USER"], "userName": "ligoj-admin"
}
```

### whoami

Return user identifier

```bash
ligoj session whoami
```

```json
{"id": "ligoj-admin"}
```


## System User

A system user can live without federated identity. After a successful login, a federated user can be managed with system roles and API keys.


### Create a system user 

Create a new system user with role names or identifiers.

```bash
ligoj user upsert --id ligoj-admin@sample.com --roles USER ADMIN
```

Optionally, at this time, an API key is generated but only once and only from administrator users.

```bash
ligoj user upsert --id ligoj-admin@sample.com --roles USER ADMIN --api_key_name cli
```

Output the API key only if not existing.

```json
{"id": "__api_key__", "name": "cli"}
```

*Note* When role names are provided API calls are executed to retrieve their identifiers.

### Delete a system user

Delete a system user. The command will not fail if the user is not found.

```bash
ligoj user delete --id ligoj-user
```


### List system users

```bash
ligoj user list
ligoj user list --with-roles
```

```json
{"recordsTotal": 3, "recordsFiltered": 3, "data": ["ligoj-admin", "ligoj-admin@sample.com", "ligoj-user"]}
```

*Note* When role names are provided API calls are executed to retrieve their identifiers.


### Delete a system user 

Create a new system user with role names or identifiers.

```bash
ligoj user delete --id ligoj-user
```


## System Role

A system role holds the permissions (ui and api), and can be assigned to users or groups.


### Create a system role 

Create or update a system role.

**Note** Whereas Ligoj supports per HTTP method authorizations, this feature is not yet available from this CLI action.

```bash
# Deprecated `--id` option
ligoj role create --id ADMIN --api ".*" --ui ".*"
ligoj role create --name ADMIN --api ".*" --ui ".*"
ligoj role create --name SELF_TOKEN_RENEW --api "/api/token.*" --ui "/sys/token"
```

Output is the created/existing role identifier.
```json
123
```

### Delete a system role

Delete a system role. The command will not fail if the role does not exist.

```bash
ligoj role delete --id 1
ligoj role delete --name ADMIN
```

### List system roles

```bash
ligoj role list
```

### Get a system role

```bash
ligoj role get --id 1
ligoj role get --name ADMIN
```

```json
{"id": 1, "createdBy": "_system", "createdDate": 1758279349911, "lastModifiedBy": "_system", "lastModifiedDate": 1758279349911, "name": "ADMIN"}
```

## Info

### Status 

Return API server status

```bash
ligoj info status
```

```json
{"status": "UP"}
```

Optionally, a wait for status can be defined. A regular poll to the server [status](#status) is performed until reaching `DOWN` or `UP` status.
When different from `0`, the final status is returned.

```bash
ligoj info status --wait 20
```

```json
{"status": "DOWN"}
```

### Version

Return API server version

```bash
ligoj info version
ligoj --version
ligoj -v
```

```json
{"version": "3.3.1-SNAPSHOT"}
```


### API Specification

All Ligoj APIs are accessible with REST verbs.

Currently 3 specification formats are available:
- Swagger : Web UI based on OpenAPI JSON file
- OpenAPI JSON file
- [WADL](https://www.w3.org/submissions/wadl/)

```bash
ligoj info api --output openapi --print content
ligoj info api
```

```json
{
  "openapi" : "3.0.1",
  "info" : {
    "title" : "Ligoj API application",
    "description" : "REST API services of application. Includes the core services and the features of actually loaded plugins",
    "contact" : {
      "name" : "The Ligoj team",
      "url" : "https://github.com/ligoj"
```

```bash
ligoj info api --output wadl --print url
ligoj info api --output openapi --print url
ligoj info api --output swagger --print url
```

```text
http://localhost:8080/ligoj/rest?_wadl
http://localhost:8080/ligoj/rest/openapi.json
http://localhost:8080/ligoj/api-docs?url=openapi.json
```

## Token

Manage API keys of current user.

### Create a token

For `expiration` option:
- Either a full ISO date, which corresponds to the furthest date the generated token can be trusted.
- Either a duration starting from now, in a standard duration format. See [pytimeparse](https://pypi.org/project/pytimeparse/)

Expired tokens are neither listed nor returned even if they are not yet physically deleted.

```bash
ligoj token create --id cli_init
ligoj token create --id today_only --expiration 1d
ligoj token create --id SELF_TOKEN_RENEW --expiration 2029-12-31T23:59:59
```

Optionally, the created token can be saved into the current profile, replacing any previously existing one:

Output:

```json
{"id": "__api_key__", "name": "cli_init"}
```

### List tokens

```bash
ligoj token list

["cli_init", "test"]
```

### Get a token value

```bash
ligoj token get --id cli_init

```json
{"value": "__api_key__"}
```

### Delete a token value

```bash
ligoj token delete --id cli_init
```

### Version

Return API server version

```bash
ligoj info version
ligoj --version
ligoj -v
```

```json
{"version": "3.3.1-SNAPSHOT"}
```


## Configuration

Configure global values

### Set value

```bash
ligoj configuration set --id "foo" --value "bar"
ligoj configuration set --id "plugins.repository-manager.nexus.search.url" --value "https://localhost/?g:org.ligoj.plugin"
ligoj configuration set --id "plugins.repository-manager.nexus.search.proxy.host" --value "my-proxy.local"
ligoj configuration set --id "plugins.repository-manager.nexus.search.proxy.port" --value "8080"
ligoj configuration set --id "plugins.repository-manager.nexus.artifact.url" --value "https://nexus.localhost:8443/repository/maven_corporate/org/ligoj/plugin/"
ligoj configuration set --id "cache.id-ldap-data.ttl" --value "3600"

```


*Note* When you change a configuration related to plugin management, invalidate the related caches to retrieve the up-to-date plugin versions.

### Get value

Return the configuration value from its `id`, which can be a Java property name or a stored value in the `S_CONFIGURATION` table.

Return a specific value. Encrypted values are returned as decrypted.

```bash
ligoj configuration get --id "foo"
```

```json
{"value": "bar"}
```

Return all values. Encrypted values are not returned.

```bash
ligoj configuration get
```

```json
[{"name": "COMMAND_MODE", "value": "unix2003", "persisted": false, "secured": false, "overridden": false, "source": "systemEnvironment"},...]
```

### Delete value

```bash
ligoj configuration delete --id "foo"
```

## Cache

### Invalidate cache

```bash
ligoj cache invalidate --id "node-parameters"
ligoj cache invalidate --id "nodes"
ligoj cache invalidate --id "iam-node-configuration"
ligoj cache invalidate --id "id-ldap-data"
ligoj cache invalidate --id "user-details"
ligoj cache invalidate --id "plugins-last-version-nexus"
ligoj cache invalidate
```

### Get cache details

```bash
ligoj cache get --id "user-details"
```

```json
{
    "id": "user-details", 
    "size": 1, 
    "hitCount": 123, 
    "missCount": 14, 
    "hitPercentage": 89.78102, 
    "missPercentage": 10.218978, 
    "averageGetTime": 16.860365, 
    "node": {"id": "00000000-0000-0000-0000-000000000000", "address": "[127.0.0.1]:5701", "version": "5.3.2", "cluster": {"id": "00000000-0000-0000-0000-000000000001", "state": "ACTIVE", "members": [{"id": "00000000-0000-0000-0000-000000000000", "address": "[127.0.0.1]:5701", "version": "5.3.2"}]}}
}
```

```bash
ligoj cache list
```
```json
[
    {"id": "terraform-version", "size": 0, "hitCount": 0, "missCount": 0, "hitPercentage": 0.0, "missPercentage": 0.0, "averageGetTime": 0.0, "node": {"id": "00000000-0000-0000-0000-000000000000", "address": "[127.0.0.1]:5701", "version": "5.3.2", "cluster": {"id": "00000000-0000-0000-0000-000000000001", "state": "ACTIVE", "members": [{"id": "00000000-0000-0000-0000-000000000000", "address": "[127.0.0.1]:5701", "version": "5.3.2"}]}}},
    ...
]
```

## File

A [file](https://github.com/ligoj/ligoj/blob/master/DOC.md#hook) is a remote file readable and/or writable by the API container.

Related path must be authorized by the configuration value `ligoj.file.path`. This check is performed at upload and download times.

```bash
ligoj configuration set --id "ligoj.file.path" --value "^/home/files/.*,^/home/hooks/.*,^/home/ligoj/META-INF/resources/webjars/.*,^/home/ligoj/statics/.*"
```

### Create or update file

Upload a local file to a remote file.

```bash
# Served by UI container, this file will be available from the URL: '/some/icon.png'
ligoj file put --from https://path/to/icon.png --path "/home/ligoj/statics/some/icon.png"

# Served by API container, this file will be available from the URL: '/home/img/logo.svg'
ligoj file put --from docs/ui/logo.svg --path "/home/ligoj/META-INF/resources/webjars/home/img/logo.svg"
```

### Delete file

```bash
ligoj file delete --path "/home/ligoj/icon.png"
```

### Hook get

Download a remote file and save it to a local file.

```bash
ligoj file get --path "/home/ligoj/icon.png"  --out "./icon2.png"
```

## Hook

A [hook](https://github.com/ligoj/ligoj/blob/master/DOC.md#hook) is a command uploaded by a user, and triggered by a successfully invoked API call of Ligoj.

When this command is executed, it receives a `PAYLOAD` event as environment variable.

Related command must be authorized by the configuration value `ligoj.hook.path`. This check is performed at creation and execution time: 

```bash
ligoj configuration set --id "ligoj.hook.path" --value "^/home/ligoj/hooks/.*"
ligoj configuration set --id "ligoj.file.path" --value "^/home/ligoj/hooks/.*"
ligoj file put --from docs/sample_hook_ligoj_audit.sh  --path "/home/ligoj/hooks/ligoj_audit.sh"  --executable
```

Payload structure:

```json
{
  "name":"audit_role_change",
  "now":"2023-10-17T19:22:21Z",
  "result":{"some_json":"some_value"},
  "path":"system/security/role",
  "api":"RoleResource#update",
  "params":[{"id":2652, "name":"ADMIN_PROJECT1A"}, {}],
  "method":"PUT",
  "user":"ligoj-admin",
  "timeout":30,
  "inject": {"secret1":"value1","secret2":"value2"}
}'
```

### Create hook

```bash
# Asynchronous hook
ligoj hook upsert --name "audit_role_change" --command "/home/ligoj/hooks/ligoj_audit.sh" --directory /var/log --timeout 10 --match '{"path":"system/security/role.*"}' --inject secret1 secret2

# Synchronous hook
ligoj hook upsert --name "audit_role_change" --command "/home/ligoj/hooks/ligoj_audit.sh" --directory /var/log --timeout 10 --match '{"path":"system/security/role.*", "method":"POST"}' --inject secret1 secret2 --delay 0
```

**Note** 
- For Docker image runtime, this program is executed by the container `ligoj-api`, and must be resolvable. Either this program is already packaged in the container, or it is mounted as a Docker volume to the host. Usually the mounted volume is `/home/ligoj` and points to the host path such as `/var/path/to/ligoj`. In the above hook sample, the user-level script would be `/var/path/to/ligoj/ligoj_audit.sh`.
- `--name` The human readable hook name. Is displayed in logs and HTTP headers of synchronous executions.
- `--command` The command to execute. Must be allowed by `ligoj.hook.path` configuration. This condition is checked at creation and execution time.
- `--directory` The working directory where the hook is executed.
- `--inject` Can relate to any configuration names supported by the [configuration get](#configuration) command and will be provided in the payload variable.
- `--match` Must be a valid JSON stringified object having :
  * at least the `path` property relating to a valid regular expression matching to one of the available Ligoj's endpoint.
  * an optional `method` property corresponding to ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "TRACE"].
- `--delay` The delay in seconds before the hook is executed. Default to `1`. Use `0` for synchronous hooks.
- `--timeout` The timeout in seconds before the hook is executed. Default to `10`.

Sample executable hook script `/home/ligoj/ligoj_audit.sh`:

```bash
#!/bin/bash
payload="$(echo "$PAYLOAD" | base64 -d)"
echo "$(echo "$payload"|jq -r '.now') $(echo "$payload"|jq -r '.method') $(echo "$payload"|jq -r '.path') [$(echo "$payload"|jq -r '.user')]" >> ligoj_audit.log
```

For Docker runtime, to verify this hook would run as expected, try the following command from the host:

```bash
docker exec ligoj-api jq --version
# > jq-1.6
docker exec ligoj-api python3 --version
# > Python 3.11.5
```

### Update hook

For update, `id` or `name` can be used. However, if `name` needs to be updated, provide the `id` as well.

```bash
ligoj hook upsert --id 4 --name "audit_role_change_new" --command "$(pwd)/docs/sample_hook_ligoj_audit.sh" --directory  /var/log --match '{"path":"system/security/role.*"}' --inject "feature:iam:node:primary"  "my-secret"
```

### Delete hook

Deletion can be done by `id` or `name` attribute:

```bash
ligoj hook delete --id 2
ligoj hook delete --name "audit_role_change"
```

### Hook get

Optional `id` or `name` filters are accepted:


```bash
ligoj hook get
ligoj hook get --id 1
ligoj hook get --name "audit_role_change"
```

```json
[{"id": 1, "name": "audit_role_change", "workingDirectory": "/var/log", "command": "/path/to/ligoj_audit.sh", "match": "{\"path\":\"system/security/role.*\"}", "injects": ["java.class.path"]}]
```


## Plugin

### List Ligoj plugins

```bash
ligoj plugin list
```

```json
[
    {
        "id": "feature:ui",
        "name": "Ui",
        "plugin": {
            "id": 4,
            "createdBy": "_system",
            "createdDate": 1758279349900,
            "lastModifiedBy": "_system",
            "lastModifiedDate": 1762277251346,
            "version": "2025-10-31T14:25:16.306432087Z",
            "key": "feature:ui",
            "artifact": "plugin-ui",
            "basePackage": "org.ligoj.app.plugin.ui",
            "type": "FEATURE"
        },
        "location": "/path/to/ligoj-plugins/plugin-ui/target/classes/",
        "deleted": false,
        "nodes": 0,
        "subscriptions": 0
    },
    ...
    {
        "id": "service:id:ldap",
        "name": "Ldap",
        "plugin": {
            "id": 155,
            "createdBy": "_system",
            "createdDate": 1762277251427,
            "lastModifiedBy": "_system",
            "lastModifiedDate": 1762450362232,
            "version": "2025-11-05T22:06:40.787627578Z",
            "key": "service:id:ldap",
            "artifact": "plugin-id-ldap",
            "basePackage": "org.ligoj.app.plugin.id.ldap.resource",
            "type": "TOOL"
        },
        "location": "/path/to/ligoj-plugins/plugin-id-ldap/target/classes/",
        "nodes": 2,
        "node": {
            "id": "service:id:ldap",
            "name": "Identity LDAP",
            "refined": {"id": "service:id","name": "Identity", "mode": "create", "uiClasses": "far fa-id-badge"},
            "mode": "all"
        },
        "subscriptions": 5
    }
]
```

### Install Ligoj plugins

When an explicit version is not provided, the latest version available from Maven Central is used. 

This lookup depends on the `plugins.repository-manager.nexus.search` configuration, while the download relies on `plugins.repository-manager.nexus.artifact` configuration.

```bash
ligoj plugin install --id "plugin-id" --repository "central" --version "2.2.10" --force
ligoj plugin install --id "plugin-id" --version "LATEST" --repository "nexus"
ligoj plugin install --id "plugin-id-ldap" --version "2.1.1" --repository "nexus" --force
ligoj plugin install --id "plugin-req-squash"
ligoj plugin install --id "plugin-req"
```

```log
[INFO ] [ligoj] Plugin 'plugin-req' has been installed/updated, a restart is required
```

Two successful consecutive executions give this output:

```log
[INFO ] [ligoj] Plugin 'plugin-id-ldap:2.0.3' is being installed
[INFO ] [ligoj] Plugin 'plugin-req:1.0.1' is installed but requires a restart to be available
```

*Note* After installing plugins, a restart is needed to use them.

### Restart API

```bash
ligoj plugin restart
```

```json
null
```

Optionally, a wait for status can be defined. A regular poll to the server [status](#status) is performed until reaching `DOWN` or `UP` status.
When different from `0`, the final status is returned.

```bash
ligoj plugin restart --wait 20
```

```json
{"status": "UP"}
```

## Node


### List nodes

```bash
ligoj node list
```

```json
{
  "recordsTotal": 23, 
  "recordsFiltered": 23, 
  "data": [
    {"id": "service:build", "name": "Build", "mode": "link", "uiClasses": "fa fa-cogs", "enabled": true}, 
    {"id": "service:build:jenkins", "name": "Jenkins", "refined": {"id": "service:build", "name": "Build", "mode": "link", "uiClasses": "fa fa-cogs"}, "mode": "all", "uiClasses": "fab fa-jenkins", "enabled": true}, 
    ...
    ]
}
```

Optionally, parameters can be returned with provided mode and other filters

```bash
ligoj node list --parameters-mode "all"
ligoj node list --parameters-mode "all" --search jenkins
ligoj node list --parameters-output "map" --refined "service:build:jenkins"
```

```json
{
  "recordsTotal": 23, 
  "recordsFiltered": 23, 
  "data": [
    {"id": "service:build", "name": "Build", "mode": "link", "uiClasses": "fa fa-cogs", "enabled": true, "parameters": []}, 
    {"id": "service:build:jenkins", "name": "Jenkins", "refined": {"id": "service:build", "name": "Build", "mode": "link", "uiClasses": "fa fa-cogs"}, "mode": "all", "uiClasses": "fab fa-jenkins", "enabled": true, "parameters": []}, 
    {"id": "service:build:jenkins:local", "name": "Jenkins Local", "refined": {"id": "service:build:jenkins", "name": "Jenkins", "refined": {"id": "service:build", "name": "Build", "mode": "link", "uiClasses": "fa fa-cogs"}, "mode": "all", "uiClasses": "fab fa-jenkins"}, "mode": "all", "enabled": true, 
      "parameters": [
        {"text": "-secured-", "parameter": "service:build:jenkins:api-token"}, {"text": "http://localhost:9190/", "parameter": "service:build:jenkins:url"}, 
        {"text": "-secured-", "parameter": "service:build:jenkins:user"}
      ]
    },
    ...
  ]
}
```

### Configure/update a node


If the related node already exists, it is updated.

```bash
ligoj node upsert --id "service:id:ldap:remote1" --name "Remote1" --from ligoj-ldap.json
ligoj node upsert --id "service:id:ldap:remote1" --name "Remote1" --from https://path/to/ligoj-ldap.json
```

```json
{"id": "service:id:ldap:remote1", "name": "Remote1", "mode": "all", "enabled": true}
```

Input `--from` JSON:
- See [`--from`](#--from) for JSON loading options
- JSON can be as list or dict (compact). See sample.
- The parameters marked as sensitive are encrypted in database of Ligoj.

Content of sample [ligoj-ldap.json](docs/nodes/ldap.json) file:

```json
[
  {
      "parameter": "service:id:ldap:base-dn",
      "text": "cn=Test"
  },
  {
      "parameter": "service:id:ldap:uid-attribute",
      "text": "uid"
  }
]
```


### Get node by identifier

```bash
ligoj node get --id "service:id"
ligoj node get --id "service:id:ldap"
ligoj node get --id "service:id:ldap:remote1"
```

```json
{"id": "service:id:ldap:remote1", "name": "Remote1", "mode": "all", "enabled": true}
```

Optionally, parameters can be returned with provided mode

```bash
ligoj node get --id "service:id" --parameters-mode "all"
ligoj node get --id "service:id:ldap" --parameters-mode "all"
ligoj node get --id "service:id:ldap:remote1" --parameters-mode "all"
```

```json
{
  "id": "service:id:ldap:remote1", "name": "Remote1", "mode": "all", "enabled": true,
  "parameters": [
    {"text": "cn=Test", "parameter": "service:id:ldap:base-dn"}, {"bool": true, "parameter": "service:id:ldap:clear-password"}, 
    {"text": "organizationalUnit", "parameter": "service:id:ldap:companies-class"},
    {"text": "-secured-", "parameter": "service:id:ldap:user-dn"}]
}
```

Optionally, parameters can be returned with more details

```bash
ligoj node get --id "service:id:ldap:remote1" --parameters-mode "all" --parameters-output "full"
```

```json
{
  "id": "service:id:ldap:remote1", "name": "Remote1", "mode": "all", "enabled": true,
  "parameters": [{
        "parameter": {
            "id": "service:id:group",
            "type": "text",
            "owner": {
                "id": "service:id",
                "name": "Identity",
                "mode": "create",
                "uiClasses": "far fa-id-badge"
            },
            "mandatory": true,
            "secured": false,
            "depends": []
        }
    },
    {
        "text": "cn=Test",
        "parameter": {
            "id": "service:id:ldap:base-dn",
            "type": "text",
            "owner": {
                "id": "service:id:ldap",
                "name": "Identity LDAP",
                "refined": {
                    "id": "service:id",
                    "name": "Identity",
                    "mode": "create",
                    "uiClasses": "far fa-id-badge"
                },
                "mode": "all"
            },
            "mandatory": false,
            "secured": false,
            "depends": []
        }
    }
  ]
}
```

Optionally, parameter values can be decrypted. One API call is performed for each secured value.

This mode is only available for users having `ADMIN` role.

```bash
ligoj node get --id "service:id:ldap:remote1" --parameters-mode "all" --parameters-output map --parameters-secured
```

```json
{
  "id": "service:id:ldap:remote1", "name": "Remote1", "mode": "all", "enabled": true, 
  "parameters": {
    "service:id:ldap:base-dn": "cn=Test",
    "service:id:ldap:clear-password": true,
    "service:id:ldap:url": "ldap:localhost:1389",
    "service:id:ldap:password": "secret",
    "service:id:ldap:companies-class": "organizationalUnit", 
    "service:id:ldap:companies-dn": "ou=people,dc=sample,dc=com"
  }
}
```

### Get node status

```bash
ligoj node status --id "service:id:ldap:remote1"
```

```json
{"id": "down"}
```

## Delegate node

Node delegates allow users, groups or companies to manage nodes.

Sub nodes inherit the delegate permissions.

### List delegate nodes

```bash
ligoj delegate-node list
```

```json
[
  {"id": 1, "createdBy": "_system", "createdDate": 1758279349979, "lastModifiedBy": "_system", "lastModifiedDate": 1758279349979, "name": "service", "receiver": "ligoj-admin", "receiverType": "user", "canWrite": true, "canAdmin": true, "canSubscribe": true, "referenceID": "service"}
]
```

### Create delegate node

Create a delegate with subscribe, administration, and creation rights for a receiver on an optional node and its sub-nodes.

The provided node does not need to exist yet.

```bash
ligoj delegate-node create --node service --can-subscribe --can-admin --can-write --receiver jdoe --receiver-type user
ligoj delegate-node create --node service:id --can-subscribe --receiver internal --receiver-type company
ligoj delegate-node create --node service:id:ldap:instance1 --can-admin --can-write --receiver group1 --receiver-type group
```

### Delete delegate node

Delete a delegate node from its identifier.

```bash
ligoj delegate-node delete --id 1
```

### Get a delegate node

Get a delegate node from its identifier.

```bash
ligoj delegate-node get --id 1
ligoj delegate-node get --node 1
```


## Project

### List projects

List projects with optional search criteria.

```bash
ligoj project list
ligoj project list --search project1
```

```json
{
  "recordsTotal": 1, 
  "recordsFiltered": 1, 
  "data": [
    {
      "id": 153, 
      "createdDate": 1705853880193, "lastModifiedDate": 1705853880193, 
      "createdBy": { "id": "ligoj-admin", ...}, 
      "lastModifiedBy": {"id": "ligoj-admin", ...}, 
      "name": "Project 1",
      "teamLeader": {"id": "ligoj-admin", ...}, 
      "pkey": "project1", 
      "description": "",
      "nbSubscriptions": 2
    },
    ...
  ]
}
```
### Get Project

```bash
ligoj project get --id 153
ligoj project get --id "project1"
```

```json
{
  "id": 153, 
  "createdDate": 1705853880193, "lastModifiedDate": 1705853880193, 
  "createdBy": { "id": "ligoj-admin", ...}, 
  "lastModifiedBy": {"id": "ligoj-admin", ...}, 
  "name": "Project 1",
  "teamLeader": {"id": "ligoj-admin", ...}, 
  "pkey": "project1", 
  "description": "",
  "manageSubscriptions": true, 
  "subscriptions": [
    {"id": 355, ...},
    {"id": 362, ...}
  ]
}
```

### Create Project

```bash
ligoj project create --name "project4" --team-leader "ligoj-admin" --pkey "sample:project4" --description "Sample project 4" --context='{"some":"value"}'
```

```json
{
  "id": 352, 
  "creationContext": "{\"some\":\"value\"}", 
  "name": "project4", 
  "teamLeader": {"id": "ligoj-admin",...},
  "pkey": "sample:project4", 
  "description": "Sample project 4",
  ...
}
```

### Delete Project

Delete project with optional search criteria.

```bash
ligoj project delete --id 252
ligoj project delete --id "sample:project4"
ligoj project delete --id "sample:project4" --with-data
```


## Subscription operations

### List subscriptions

Combined filters are accepted.

```bash
ligoj subscription list --node "service:id:ldap:remote1"
ligoj subscription list --tool "service:id:ldap"
ligoj subscription list --service "service:id"
ligoj subscription list --project "project1"
ligoj subscription list --project 104
```

```json
[
  {"id": 155, "node": "service:id:ldap:remote1", "project": 104}, 
  {"id": 302, "node": "service:qa:sonarqube:8", "project": 104}
]
```

### Get subscription details

```bash
ligoj subscription get --id 302
```

```json
{"service:qa:sonarqube:project": "test", "service:qa:sonarqube:url": "http://127.0.0.1:9000/"}
```

#### With related project and node details

```bash
ligoj subscription get --id 302 --details
```

```json
{"subscription": 302, "project": {"id": 104, "name": "Project1", "description": "Foo bar"}, "parameters": {"service:qa:sonarqube:project": "test", "service:qa:sonarqube:url": "http://127.0.0.1:9000/"}, "node": {"id": "service:qa:sonarqube:8", "name": "Sonar Local 8", "refined": {"id": "service:qa:sonarqube", "name": "SonarQube", "refined": {"id": "service:qa", "name": "Quality Assurance", "mode": "link", "uiClasses": "fas fa-tachometer-alt"}, "mode": "link"}, "mode": "link", "enabled": true}}
```

### Create subscription

Configuration file can be a JSON file, a remote HTTP URL, or plain JSON.  Both forms of parameters are accepted, as list or dict (compact).

Duplicate subscriptions are ignored: same project, node and parameters.

```bash
ligoj subscription create --project project1 --node "service:id:ldap:remote1" --from conf.json
ligoj subscription create --project project1 --node "service:id:ldap:remote1" --from "https://path/to/conf.json"
ligoj subscription create --project project1 --node "service:id:ldap:remote1" --from '[{"parameter": "service:id:group", "text": "project1-team"}, {"parameter": "service:id:ou", "text": "project1"}]'
ligoj subscription create --project project1 --node "service:id:ldap:remote1" --from '{"service:id:group": "project1-team", "service:id:ou": "project1"}'
...
```

```json
362
```

Input `--from` JSON:
- See [`--from`](#--from) for JSON loading options
- JSON can be as list or dict (compact). See sample.
- The parameters marked as sensitive are encrypted in database of Ligoj.

### Delete a subscription

Delete a subscription from its identifier. 


```bash
ligoj subscription delete --id 302
```

By default, only the link between Ligoj and the remote tool is removed. Optionally, when Ligoj has created data with the subscription, it can also be deleted with this operation.

For example, LDAP groups or a Jenkins job created at subscription time will be deleted.

```bash
ligoj subscription delete --id 302 --with-data
```

### Get subscription statuses of a project

Return the last computed status of all subscriptions of given project.

```bash
ligoj subscription status --project 104
ligoj subscription status --project project1
```

```json
{
  "155": {"specifics": [], "value": "UP", "type": "status", "node": {"id": "service:id:ldap:remote1", "name": "TestAnnuaireCLI", "mode": "all"}, "subscription": 155}, 
  "252": {"specifics": [], "value": "DOWN", "type": "status", "node": {"id": "service:qa:sonarqube:user", "name": "Sonar Local User", "mode": "link"}, "subscription": 252},
  "157": {"specifics": [], "value": "UP", "type": "status", "node": {"id": "service:id:ldap:remote1", "name": "TestAnnuaireCLI", "mode": "all"}, "subscription": 157}
}
```

### Request subscription status refresh

Retrieve the up-to-date status of a subscription.


Up subscription:

```bash
ligoj subscription refresh --id 155
```

```json
{"id": 155, "status": "up", "node": "service:id:ldap:remote1", "project": 104, "data": {"members": 0}, "parameters": {...}}
```

Down subscription:
```bash
ligoj subscription refresh --id 252
```

```json
{"id": 252, "status": "down", "project": 104, "data": {}, "parameters": {"service:qa:sonarqube:project": "test",...}}
```


# Plugin id

Operations related to [plugin-id](https://github.com/ligoj/plugin-id) and sub-plugins.


## Plugin `id:scope` operations

Operations related to container scopes managed by `service:id` nodes.


### Create container scope

Create a container scope

```bash
ligoj id:scope create --id "Unassigned" --type "group" --dn "ou=groups,dc=example,dc=com"
ligoj id:scope create --id "Projects" --type "group" --dn "ou=project,ou=groups,dc=example,dc=com"
ligoj id:scope create --id "Tools" --type "group" --dn "ou=tools,ou=groups,dc=example,dc=com"
ligoj id:scope create --id "Unassigned" --type "company" --dn "ou=people,dc=example,dc=com"
ligoj id:scope create --id "Internal" --type "company" --dn "ou=internal,ou=people,dc=example,dc=com"
ligoj id:scope create --id "Unassigned" --type "tree" --dn "dc=example,dc=com"
```


### Get container scope

Return a container scope

```bash
ligoj id:scope get --id "SampleGroup2"
```

```json
{"id": "samplegroup2", "name": "SampleGroup2", "scope": "Unassigned", "locked": false}
```


### List container scopes

Return a list of container scopes

```bash
ligoj id:scope list --type "group"
```

```json
{
  "recordsTotal": 4, "recordsFiltered": 3, 
  "data": [
    {"id": 5, "name": "Unassigned", "dn": "ou=groups,dc=sample,dc=com", "type": "group", "locked": false}, 
    {"id": 6, "name": "Project", "dn": "ou=project,ou=groups,dc=sample,dc=com", "type": "group", "locked": false}, 
    {"id": 7, "name": "Technical", "dn": "ou=tools,ou=groups,dc=sample,dc=com", "type": "group", "locked": false}
  ]
}
```

## Plugin `id:group` operations

Operations related to groups managed by `service:id` nodes

Group name is case insensitive.


### Create group

Create a group.


```bash
ligoj id:group create --name "SampleGroup2" --scope "Unassigned"
```

Create a group inside a group

```bash
ligoj id:group create --name "SampleSubGroup" --scope "Unassigned" --parent "SampleGroup2"
ligoj id:group create --name "SampleSubGroup2" --scope "Unassigned" --parent "SampleSubGroup"
```


### Delete a group

Delete a group. The command will not fail if the group does not exist.

```bash
ligoj id:group delete --name "SampleGroup2"
```


### Get group

Retrieve a group

```bash
ligoj id:group get --name "SampleGroup2"
```

```json
{"id": "samplegroup2", "name": "SampleGroup2", "scope": "Unassigned", "locked": false}
```

### Delete group

Delete a group. If the group does not exist, the command will not return an error.

```bash
ligoj id:group delete --name "SampleGroup2"
```


### List group

List groups

```bash
ligoj id:group list
```

```json
{
    "recordsTotal": 4,
    "recordsFiltered": 4,
    "data": [
        {
            "id": "sample group",
            "name": "Sample Group",
            "scope": "Unassigned",
            "locked": false,
            "countVisible": 3,
            "count": 3,
            "canWrite": true,
            "canAdmin": true,
            "containerType": "group"
        },
        {
            "id": "samplegroup2",
            "name": "SampleGroup2",
            "scope": "Unassigned",
            "locked": false,
            "countVisible": 0,
            "count": 0,
            "canWrite": true,
            "canAdmin": true,
            "containerType": "group"
        },
        {
            "id": "samplesubgroup",
            "name": "SampleSubGroup",
            "scope": "Unassigned",
            "locked": false,
            "countVisible": 0,
            "count": 0,
            "canWrite": true,
            "canAdmin": true,
            "containerType": "group",
            "parents": [
                "samplegroup2"
            ]
        },
        {
            "id": "samplesubgroup2",
            "name": "SampleSubGroup2",
            "scope": "Unassigned",
            "locked": false,
            "countVisible": 0,
            "count": 0,
            "canWrite": true,
            "canAdmin": true,
            "containerType": "group",
            "parents": [
                "samplesubgroup",
                "samplegroup2"
            ]
        }
    ]
}
```

## Plugin `id:user` operations

Operations related to users managed by `service:id` nodes


### Create user

```bash
ligoj id:user create --id jdupont --firstname "Jean" --lastname "Dupont" --mail "jdupont@kloudy.io" --company "external" --groups "Sample Group,SampleGroup2"
ligoj id:user create --id jdupont2 --firstname "Jean" --lastname "Dupont" --mail "jdupont@kloudy.io" --company "external" --groups "Sample Group,SampleGroup2"
```

### Delete user

Delete a user. If the user does not exist, the command will not return an error.

```bash
ligoj id:user delete --id jdupont2
ligoj id:user delete --mail jdupont@kloudy.io
```

### List users

```bash
ligoj id:user list
ligoj id:user list --company "department1" --group "Sample Group" --criteria "@sample.com" --page-length 2
ligoj id:user list --company "department1" --page-length 2
```

```json
{
  "recordsTotal": 102, 
  "recordsFiltered": 102,
  "extensions": {"customAttributes": ["uidFonctionnel"]}},
  "data": [
    {"firstName": "John", "lastName": "Doe", "id": "jdoe", "company": "external", "mails": ["jdoe@sample.com"], "groups": ["Sample Group", "SampleGroup2"], "name": "jdoe"}, 
    {"firstName": "Cli2", "lastName": "Name", "id": "cli2name", "company": "external", "mails": ["a@bc.org","cli2@sample.com"], "groups": ["Sample Group"], "name": "cli2name"}
  ]
}
```
### Get user

Return a user. If the user does not exist, the command will return `null`.

```bash
ligoj id:user get --id jdupont
ligoj id:user get --mail jdupont@kloudy.io
```

```json
{"firstName": "Jean", "lastName": "Dupont", "id": "jdupont", "company": "external", "mails": ["jdupont@kloudy.io"], "groups": ["Sample Group", "SampleGroup2"], "name": "jdupont"}
```

### Add user to a group

The user and the group must exist.
The command does not fail if the user is already in the group.

```bash
ligoj id:user add --id jdupont --groups "SampleGroup2"
ligoj id:user add --mail jdupont@kloudy.io --groups "SampleGroup2"
ligoj id:user add --mail cli10.name@sample.com --groups "Sample Group"
```

### Remove user from a group

The user and the group must exist.
The command does not fail if the user is not in the group.

```bash
ligoj id:user remove --id jdupont --groups "SampleGroup2"
ligoj id:user remove --mail jdupont@kloudy.io --groups "SampleGroup2"
```

### Reset user password

For a specific user (need administrative rights):

The user must exist.

```bash
ligoj id:user reset-password --id jdupont
ligoj id:user reset-password --mail jdupont@kloudy.io
```

For current user:

```bash
ligoj id:user reset-password
```

# Bootstrap

The following commands can be executed to perform several API commands following a complex workflow.

Most bootstrap arguments like `--jenkins-endpoint`, corresponding [configuration file](#configuration-files) option such as `jenkins_endpoint` is accepted, and environment variable `JENKINS_ENDPOINT` too.


## Bootstrap `init`

Initialize Ligoj with basic group management, containers, and companies hierarchy.

Sample Docker command: 

```bash
ligoj bootstrap init --base-dn="dc=sample,dc=com"
```

*Note* `--base-dn` argument can also be defined as `ligoj_ldap_base_dn` in [configuration file](#configuration-files) and `LIGOJ_LDAP_BASE_DN` environment variable.


Hierarchy tree sample for base DN `dc=sample,dc=com`


| DN LDAP                                                                              | Scope name   | Scope type |
| ------------------------------------------------------------------------------------ | ------------ | ---------- |
| `ou=people`                                                                          | `Unassigned` | `company`  |
| `  ou=technical-users,ou=people`                                                     | `Technical`  | `company`  |
| `  ou=external,ou=people`                                                            | `External`   | `company`  |
| `ou=groups`                                                                          | `Unassigned` | `group`    |
| `  ou=project,ou=groups`                                                             | `Project`    | `group`    |
| `  ou=tools,ou=groups`                                                               | `Technical`  | `group`    |
| `    cn=jenkins-administrators,ou=tools,ou=groups`                                   | (inherited)  | `group`    |
| `    cn=nexus-administrators,ou=tools,ou=groups`                                     | (inherited)  | `group`    |
| `      cn=nexus-administrators-paris,cn=nexus-administrators,ou=tools,ou=groups`     | (inherited)  | `group`    |
| `        cn=nexus-administrators-paris-8,cn=nexus-administrators,ou=tools,ou=groups` | (inherited)  | `group`    |


### Via `ligoj bootstrap init`

```bash
ligoj bootstrap init --base-dn="dc=sample,dc=com" --users-base-dn "ou=people" --internal-users-base-dn "" --technical-users-base-dn "ou=technical-users" --external-users-base-dn "ou=external" --groups-base-dn "ou=groups" --technical-groups-base-dn "ou=tools" --projects-base-dn "ou=project" --technical-groups "sonar-administrators" "jenkins-administrators" "nexus-administrators"
```

### Via `ligoj id` commands

```bash
## Users and companies

### OU LDAP intermediate
ligoj id:ou create --name "people" --parent-dn "dc=sample,dc=com"
ligoj id:ou create --name "external" --parent-dn "ou=people,dc=sample,dc=com"
ligoj id:ou create --name "technical-users" --parent-dn "ou=people,dc=sample,dc=com"

### Companies
ligoj id:scope create --name "Unassigned" --type "company" --dn "ou=people,dc=sample,dc=com"
ligoj id:scope create --name "External" --type "company" --dn "ou=external,ou=people,dc=sample,dc=com"
ligoj id:scope create --name "Technical" --type "company" --dn "ou=technical-users,ou=people,dc=sample,dc=com"

## Groups

### OU LDAP intermediate
ligoj id:ou create --name "groups" --parent-dn "dc=sample,dc=com"
ligoj id:ou create --name "projects" --parent-dn "ou=groups,dc=sample,dc=com"
ligoj id:ou create --name "tools" --parent-dn "ou=groups,dc=sample,dc=com"

### Scope functionals for groups
ligoj id:scope create --name "Unassigned" --type "group" --dn "ou=groups,dc=sample,dc=com"
ligoj id:scope create --name "Project" --type "group" --dn "ou=project,ou=groups,dc=sample,dc=com"
ligoj id:scope create --name "Technical" --type "group" --dn "ou=tools,ou=groups,dc=sample,dc=com"

### Technical groups and sub-groups
ligoj id:group create --name "jenkins-administrators" --scope "Technical"
ligoj id:group create --name "nexus-administrators" --scope "Technical"
ligoj id:group create --name "nexus-administrators-paris" --scope "Technical" --parent "nexus-administrators"
ligoj id:group create --name "nexus-administrators-paris-8" --scope "Technical" --parent "nexus-administrators-paris"
```


## Bootstrap `welcome-user`

Configure a new project and its administrator.

![Sequence](docs/bootstrap/welcome-user.png)

```bash
ligoj bootstrap welcome-user --id jdupont --project project1 --name "Project 1" --group-suffix="-team"
```

Optionally, the project key can be validated with DNS within a defined DNS zone :

```bash
ligoj bootstrap welcome-user --id jdupont --project project1 --name "PIProject 1" --verify-project-with-dns "PROJECT_KEY.holder.kloudy.io,PROJECT_KEY.holder2.kloudy.io" --group-suffix="-team"
```

```json
{
    "admin_user": "jdupont", 
    "script_user": "project1-script", 
    "script_api_key": "...", 
    "reader_user": "project1-reader", 
    "reader_password": "...", 
    "project_key": "project1", 
    "project_id": 6552
}
```

Optionally, Ligoj nodes such as Jenkins and SonarQube can be created during this step.

```bash
ligoj bootstrap welcome-user --id jdupont --project project1 --name "Project 1" --verify-project-with-dns "PROJECT_KEY.holder.kloudy.io,PROJECT_KEY.holder2.kloudy.io" --group-suffix="-team" --jenkins-create-node --jenkins-endpoint http://localhost:8086 --jenkins-api-token="" --sonar-create-node --sonar-endpoint http://localhost:9000  --sonar-api-token="" --reset-reader-password 
```

*Notes*
- `reader_password` result is provided only for new user and cannot be retrieved by Ligoj.
- To generate another password, use the `--reset-reader-password` flag.
- `reader_password` (or reset password) is used to create API tokens saved in Ligoj nodes
- `--jenkins-api-token` and `--sonar-api-token` can be provided with this command but should be related to the `reader_user` or `--jenkins-api-user` value.
- All endpoints and tokens are also sourced from [configuration file](#configuration-files) and environment variables.

## Bootstrap `create-project`

Create new groups within a new project related to another one.

Considering this use case :
- Create a new project having `project-a` as key and `Project A` as name.
- Team leader (administrator) will be `cli100.name@sample.com`. Actual username is resolved automatically from email.
- Initial groups within this project are `admin`, `dev` and `test`.
- The parent project's key (used as context) is `project1`. This project must be  managed by the user: `ligoj-user`

The corresponding command is:

```bash
ligoj bootstrap create-project --project project-a --name "Project A" --groups "admin" "dev" "test" \
--parent-project "project1" \
--parent-admin "ligoj-user" \
--team-leader cli100.name@sample.com \
```

*Note* When `parent-admin` is provided, this operation exploits the `run-as` feature of Ligoj to check the administrator of `parent-project`. In such a case, the session user must be a system administrator.


## Bootstrap `delete-project`

Delete a project including all groups, not only the references.

```bash
ligoj bootstrap delete-project --project project-a --parent-admin "ligoj-user"
```

*Note* When `parent-admin` is provided, this operation exploits the `run-as` feature of Ligoj to check the administrator of `parent-project`. In such a case, the session user must be a system administrator.

## Bootstrap create-roles

Create mapped roles in various tools

Supported services are:
- Jenkins
- SonarQube
- Nexus
- Alfresco
- GitLab

![Sequence](docs/bootstrap/create-roles.png)


Created contents by tools

| Tool                              | Content type            | Note                                                  |
| --------------------------------- | ----------------------- | ----------------------------------------------------- |
| [Jenkins](#jenkins)               | Folder RBAC Permissions | See [CasC notes](#security-and-configuration-as-code) |
| [Jenkins](#jenkins)               | Global RBAC Permissions | See [CasC notes](#security-and-configuration-as-code) |
| [Jenkins](#jenkins)               | Folder credentials      | See [supported credentials](#credentials)             |
| [Jenkins](#jenkins)               | Global credentials      | See [supported credentials](#credentials)             |
| [Jenkins](#jenkins)               | Folders                 | Nested `folders` structure supported                  |
| [SonarQube](#sonarqube)           | Groups and RBAC         |                                                       |
| [SonarQube](#sonarqube)           | Projects                |                                                       |
| [SonarQube](#sonarqube)           | Templates               |                                                       |
| [GitLab](#gitLab)                 | Wrapper project Groups  |                                                       |
| [GitLab](#gitLab)                 | LDAP project Groups     |                                                       |
| [GitLab](#gitLab)                 | Project Groups          |                                                       |
| [Sonatype Nexus](#sonatype-nexus) | Roles                   |                                                       |
| [Sonatype Nexus](#sonatype-nexus) | Repositories            |                                                       |
| [Alfresco](#alfresco)             | Roles                   |                                                       |
| [Alfresco](#alfresco)             | Sites                   |                                                       |
| [ArgoCD](#argocd)                 | Permissions             | Optional `permission=deny` and `application` scope    |
| [ArgoCD](#argocd)                 | Projects                |                                                       |
| [Harbor](#harbor)                 | Projects                |                                                       |
| [Harbor](#harbor)                 | Projects members        |                                                       |


Group and role configuration [JSON file conf.json](docs/bootstrap/create-roles.json).
See [`--from`](#--from) for JSON loading options

```bash
ligoj bootstrap create-roles --project project-a --from conf.json \
--argocd-token="$ARGOCD_TOKEN" \
--argocd-user="$ARGOCD_USER" \
--alfresco-endpoint="$ALFRESCO_ENDPOINT" \
--alfresco-user="$ALFRESCO_USER" \
--alfresco-password="$ALFRESCO_PASSWORD" \
--nexus-endpoint="$NEXUS_ENDPOINT" \
--nexus-user="$NEXUS_USER" \
--nexus-password="$NEXUS_PASSWORD" \
--gitlab-endpoint="$GITLAB_ENDPOINT" \
--gitlab-token="$GITLAB_TOKEN" \
--jenkins-home="$JENKINS_HOME" \
--jenkins-endpoint="$JENKINS_ENDPOINT" \
--sonar-endpoint="$SONAR_ENDPOINT" \
--sonar-api-token="$SONAR_API_KEY" \
--harbor-endpoint="$HARBOR_ENDPOINT" \
--harbor-user="$HARBOR_USER" \
--harbor-password="$HARBOR_PASSWORD"
```

```bash
ligoj bootstrap create-roles --project project-a --from "https://path/to/conf.json"
```

```bash
ligoj bootstrap create-roles --project project-a --from '[{"text": "organizationalUnit","parameter": "service:id:ldap:companies-class"},...]'
```

For detailed tool specific options, execute usage command:

```bash
ligoj bootstrap create-roles --help
```

```log
usage: Ligoj CLI bootstrap create-roles [-h] [--project PROJECT] [--group-suffix GROUP_SUFFIX] [--groups [GROUPS ...]] [--from FROM] 
  [--schema SCHEMA] 
  [--alfresco-endpoint ALFRESCO_ENDPOINT] [--alfresco-user ALFRESCO_USER] [--alfresco-password ALFRESCO_PASSWORD]
  [--alfresco-ticket ALFRESCO_TICKET] 
  [--gitlab-endpoint GITLAB_ENDPOINT] [--gitlab-token GITLAB_TOKEN] [--gitlab-base-group GITLAB_BASE_GROUP]
  [--gitlab-project-group-prefix GITLAB_PROJECT_GROUP_PREFIX] [--gitlab-project-subgroup-prefix GITLAB_PROJECT_SUBGROUP_PREFIX]
  [--jenkins-home JENKINS_HOME] [--jenkins-crumb JENKINS_CRUMB] [--jenkins-endpoint JENKINS_ENDPOINT]
  [--jenkins-api-user JENKINS_API_USER] [--jenkins-api-token JENKINS_API_TOKEN]
  ...

options:
  -h, --help            show this help message and exit
  --project PROJECT, -p PROJECT
                        Associated project key
...
```

### `--includes` and `--excludes` options

Each supported tool can be included or excluded from the bootstrap commands:
- By default, all discovered JSON's content is considered, no exclusion. Implicit `--includes "*"`.
- Special value `*` means all. 
- Multiple `includes` and `excludes` values can be provided
- The `excludes` option has higher priority than `includes`.
- When the resolved endpoint is empty or null, the tool is ignored.


### Constraints

Checked constraints:
- Referenced groups must be defined at root level. This constraint ensures a correct definition and avoids typos.
- Empty permissions set are not allowed.
- Given JSON must validate the [JSON Schema](https://json-schema.org/) [document schema.json](./schema.json).
- [JSON Schema](https://json-schema.org/) can be merged with custom additions: `--schema "JSON Schema string, file or URL"`.

Sample constraint limiting Alfresco sites to `1`: `--schema='{"properties":{"alfresco":{"properties":{"sites":{"maxItems": 1}}}}}'`

### Jenkins

Supported resources are:
- Nested folders
- Credentials with or without values
- Roles, group mapping and permissions, at folder or global level


#### Configuration

| Parameter             | Environment variable | Note                                           | Default         |
| --------------------- | -------------------- | ---------------------------------------------- | --------------- |
| `--jenkins-endpoint`  | `JENKINS_ENDPOINT`   | HTTPS endpoint                                 | Current Jenkins |
| `--jenkins-api-user`  | `JENKINS_API_USER`   | Username                                       |                 |
| `--jenkins-api-token` | `JENKINS_API_TOKEN`  | Token generated from  `/user/_me_/configure`   |                 |
|                       |                      | Sourced from Jenkins credential `JENKINS_API`. |                 |
| `--jenkins-home`      | `JENKINS_HOME`       | JENKINS home location for CasC update          |                 |
| `--jenkins-crumb`     | `JENKINS_CRUMB`      | Crumb protection enablement                    | `auto`          |

#### Folders

- Recursive folders are supported; however, each folder must be unique. This is not an implementation limit, but it makes folder reorganization possible.
- Folder maximal depth is `4`, but it is not a hard limit
- Folder names are encoded, special chars are supported
- Supported folder types are `com.cloudbees.hudson.plugins.folder.Folder` and `jenkins.branch.OrganizationFolder`. Folder mode update is not supported. Other folder modes *might* work, but have not been tested.
- There is no [permission](https://www.jenkins.io/doc/book/security/access-control/permissions/#optional-permissions) limitation; internal identifiers must be used, such as `hudson.model.Item.Build`, `hudson.model.Hudson.Administer`, etc.:
    - [Overall permissions](https://github.com/jenkinsci/jenkins/blob/master/core/src/main/java/hudson/security/Permission.java)
    - [Run permissions](https://github.com/jenkinsci/jenkins/blob/3bc62eeae933c86f6a94c940fe6f35882f1e29d5/core/src/main/java/hudson/model/Run.java#LL2593C7-L2593C7)
    - [Item permissions](https://github.com/jenkinsci/jenkins/blob/3bc62eeae933c86f6a94c940fe6f35882f1e29d5/core/src/main/java/hudson/model/Item.java#L252)
    - [SCM permissions](https://github.com/jenkinsci/jenkins/blob/3bc62eeae933c86f6a94c940fe6f35882f1e29d5/core/src/main/java/hudson/scm/SCM.java#L761)
    - [Credential permissions](https://github.com/jenkinsci/credentials-plugin/blob/b96f366e7badeedaf69724991e44409be11a07b6/src/main/java/com/cloudbees/plugins/credentials/CredentialsProvider.java#L185)
    - The naming convention for permissions is the full class name, followed by the field ([Permission](https://github.com/jenkinsci/jenkins/blob/master/core/src/main/java/hudson/security/Permission.java)) name converted to Camel case, e.g., `hudson.model.View.Read`

#### Credentials

There is no limitation for credentials type, the supported configuration is:
  - Any parameter type but file
  - Tested types are: 
      - `com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl`
      - `org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl`
      - `com.cloudbees.jenkins.plugins.sshcredentials.impl.BasicSSHUserPrivateKey`
  - Supported `scope` values are `global` and `system` (case insensitive). When not provided, the default behavior of this credential type is applied.
  - Attached domain is always `All domains`: `_`


#### Security and Configuration as Code

Requires the installed, configured and assigned Jenkins plugin [Role-based Authorization Strategy](https://plugins.jenkins.io/role-strategy/).
Underlying [role management API](https://javadoc.jenkins.io/plugin/role-strategy/com/michelin/cio/hudson/plugins/rolestrategy/RoleBasedAuthorizationStrategy.html) is executed.

CaC (Configuration as Code) [YAML file]($JENKINS_HOME/jenkins.yaml) management is supported:
- CaC file location override support is `JENKINS_CASC_FILE` variable, then `CASC_JENKINS_CONFIG` variable, then `$JENKINS_HOME/jenkins.yaml` as default.
- Only update mode is supported after all API calls, not creation
- Both current and in-memory CaC files YAML structure must contain this path: `jenkins.authorizationStrategy.roleBased.roles`
- Both current and in-memory CaC files YAML structure must contain this path: `jenkins.securityRealm.ldap.configurations`
- The script must be able to write the backup file `$path_to_cac_file.ligoj`, which will be overwritten.
- A unified diff is computed and printed for current and in-memory CaC files 
- Backup and update are executed only if there is at least one change detected in the computed unified diff
- By default, the related sub-folder access is granted from the parent folder, and the related pattern is suffixed with the `(/.*)?` expression. Set `recursive` to `false` to block this behavior.
- Roles use the folder identifier, case is insensitive

``` yml
  securityRealm:
    ldap:
      configurations:
      - displayNameAttributeName: "cn"
        groupMembershipStrategy:
          fromGroupSearch:
            filter: "(| (member={0}) (uniqueMember={0}) (memberUid={1}))"
        groupSearchBase: "ou=groups"
        groupSearchFilter: "(& (cn={0}) (| (objectClass=groupOfNames) (objectClass=groupOfUniqueNames)\
          \ (objectClass=posixGroup)))"
        inhibitInferRootDN: false
        managerDN: "cn=Manager,dc=sample,dc=com"
        managerPasswordSecret: "{...}"
        rootDN: "dc=sample,dc=com"
        server: "ldap://localhost:1389"
        userSearchBase: "ou=people"
      disableMailAddressResolver: false
      disableRolePrefixing: true
      groupIdStrategy: "caseInsensitive"
      userIdStrategy: "caseInsensitive"
```


### SonarQube

Supported resources are:
- Projects
- Template
- Roles, group mapping and permissions, at project or global level


#### Configuration

| Parameter           | Environment variable | Note                                           |
| ------------------- | -------------------- | ---------------------------------------------- |
| `--sonar-endpoint`  | `SONAR_ENDPOINT`     | HTTPS endpoint                                 |
|                     |                      | Sourced from Jenkins build parameter.          |
| `--sonar-api-token` | `SONAR_API_TOKEN`    | API key generated from `/account/security` API |
|                     |                      | - Type is `User Token`                         |
|                     |                      | - User rights : `System Administrator`         |
|                     |                      | Sourced from Jenkins credential `SONAR_API`.   |


### Sonatype Nexus

Supported resources are:
- Repository
- Roles, group mapping and permissions, at repository level or global level

Repository configuration must follow the `[/#admin/system/api](http://localhost:8681/#admin/system/api)` of your Nexus instance of:
- `POST /vi/repositories/docker/hosted`
- `POST /vi/repositories/maven/hosted`
- ...
By default, repository mode is `hosted` and can be overridden with `mode` property.


#### Configuration

| Parameter          | Environment variable | Note                                         | Default |
| ------------------ | -------------------- | -------------------------------------------- | ------- |
| `--nexus-endpoint` | `NEXUS_ENDPOINT`     | HTTPS endpoint                               |         |
|                    |                      | Sourced from Jenkins build parameter.        |         |
| `--nexus-user`     | `NEXUS_USER`         | LDAP or internal user name                   | `admin` |
|                    |                      | Sourced from Jenkins credential `NEXUS_API`. |         |
| `--nexus-password` | `NEXUS_PASSWORD`     | LDAP or internal password                    |         |
|                    |                      | Sourced from Jenkins credential `NEXUS_API`. |         |


### Harbor

Supported resources are:
- Projects
- Roles and group mapping, at project level


#### Configuration

| Parameter           | Environment variable | Note                                          | Default |
| ------------------- | -------------------- | --------------------------------------------- | ------- |
| `--harbor-endpoint` | `HARBOR_ENDPOINT`    | HTTPS endpoint                                |         |
|                     |                      | Sourced from Jenkins build parameter.         |         |
| `--harbor-user`     | `HARBOR_USER`        | LDAP or internal user name                    | `admin` |
|                     |                      | Sourced from Jenkins credential `HARBOR_API`. |         |
| `--harbor-password` | `HARBOR_PASSWORD`    | LDAP or internal password                     |         |
|                     |                      | Sourced from Jenkins credential `HARBOR_API`. |         |


### GitLab

No resources are supported, only roles. GitLab groups and sub-groups are created according to the given groups and naming guidelines.
Real Git repository projects are not managed by this CLI.

#### Configuration

| Parameter                          | Environment variable             | Note                                                                | Default  |
| ---------------------------------- | -------------------------------- | ------------------------------------------------------------------- | -------- |
| `--gitlab-endpoint`                | `GITLAB_ENDPOINT`                | HTTPS endpoint                                                      |          |
|                                    |                                  | Sourced from Jenkins global `GITLAB_ENDPOINT` environment variable. |          |
| `--gitlab-token`                   | `GITLAB_TOKEN`                   | Access token  with following constraints:                           |          |
|                                    |                                  | - Type: `Personal or Group Access Token`                            |          |
|                                    |                                  | - Scope is `${gitlab_base_group}` or root level                     |          |
|                                    |                                  | - Role: `owner` role                                                |          |
|                                    |                                  | - Access level: `api`                                               |          |
|                                    |                                  | Sourced from Jenkins credential `GITLAB_API`.                       |          |
| `--gitlab-base-group`              | `GITLAB_BASE_GROUP`              | Base group where created groups sit                                 | `/`      |
| `--gitlab-wrapper-group`           | `GITLAB_WRAPPER_GROUP`           | Path of created wrapper group. Ignored if undefined                 | `ligoj`  |
| `--gitlab-wrapper-group-name`      | `GITLAB_WRAPPER_GROUP_NAME`      | Name  of created wrapper group                                      |          |
| `--gitlab_project_subgroup_prefix` | `GITLAB_PROJECT_SUBGROUP_PREFIX` | Path prefix of created groups. No wrapper if undefined              | `ligoj-` |


#### Created hierarchy

Project hierarchy for a project `project1`:

| Gitlab path                                                          | Path pattern                                               | Default         |
| -------------------------------------------------------------------- | ---------------------------------------------------------- | --------------- |
| /base                                                                | `${gitlab_base_group}`                                     | `/`             |
| &vert;_ project1                                                     | `${gitlab_project_group_prefix}${project_key}`             | *No prefix*     |
| &nbsp;&nbsp;&nbsp;&vert;&mdash; any-repo                             | *Git repository, not managed*                              |                 |
| &nbsp;&nbsp;&nbsp;&vert;&mdash; any-group                            | *User group, not managed*                                  |                 |
| &nbsp;&nbsp;&nbsp;&vert;_ ligoj                                      | `${gitlab_wrapper_group}`                                  | `ligoj`         |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&vert;_ ligoj-project1-dev | `${gitlab-project-subgroup-prefix}${project_key}-${group}` | Prefix `ligoj-` |

Sub-groups are created with `project_creation_level` flag set to `noone` and with a specific avatar. See [GitLab API create-a-subgroup](https://docs.gitlab.com/ee/api/groups.html#create-a-subgroup)


### ArgoCD

Supported resources are:
- Projects
- Roles and permissions, at project level only
  - `action: [delete, get]`
  - `permission: [allow,deny]`, by default `allow`
  - `application:`, by default `*`

Sample JSON part:

```json
{
  "projects": [
    {
      "name": "project1",
      "description": "Project description",
      "roles": {
        "dev": {
          "permissions": [
            {
                "action": "get"
            },
            {
                "action": "delete",
                "application": "app1",
                "permission": "deny"
            }
          ]
        },
        "test": {
          "permissions": [
            {
                "action": "get"
            }
          ]
        }
      }
    }
  ]
}
```

#### Configuration

| Parameter           | Environment variable | Note                                                     |
| ------------------- | -------------------- | -------------------------------------------------------- |
| `--argocd-endpoint` | `ARGOCD_ENDPOINT`    | HTTPS endpoint.                                          |
|                     |                      | Sourced from Jenkins build parameter.                    |
| `--argocd-user`     | `ARGOCD_USER`        | Username. Not recommended, see `ARGOCD_TICKET`           |
| `--argocd-password` | `ARGOCD_PASSWORD`    | Password. Not recommended, see `ARGOCD_TICKET`           |
| `--argocd-ticket`   | `ARGOCD_TICKET`      | Ticket generated by `/alfresco/s/api/login` API          |
|                     |                      | Generated automatically if `ARGOCD_PASSWORD` is provided |
|                     |                      | Sourced from Jenkins credential `ARGOCD_API`.            |


### Alfresco

Supported resources are:
- Sites
- Roles and permissions, at site level only

```bash
ligoj bootstrap create-roles --schema='{
    "properties": {
        "groups": {
          "items": {
            "enum": [
                "dev",
                "admin",
                "test",
                "securite"
            ]
          }
        },
        "alfresco": {
            "properties": {
                "sites": {
                    "maxItems": 1
                }
            }
        }
    }
}' --project "project1" --group-suffix="-team" --from="conf/sample.conf.alfresco.json"
```


#### Configuration

| Parameter             | Environment variable | Note                                                                  |
| --------------------- | -------------------- | --------------------------------------------------------------------- |
| `--alfresco-endpoint` | `ALFRESCO_ENDPOINT`  | HTTPS endpoint.                                                       |
|                       |                      | Sourced from Jenkins global `ALFRESCO_ENDPOINT` environment variable. |
| `--alfresco-user`     | `ALFRESCO_USER`      | Username. Not recommended, see `ALFRESCO_TICKET`                      |
| `--alfresco-password` | `ALFRESCO_PASSWORD`  | Password. Not recommended, see `ALFRESCO_TICKET`                      |
| `--alfresco-ticket`   | `ALFRESCO_TICKET`    | Ticket generated by `/alfresco/s/api/login` API                       |
|                       |                      | Generated automatically if `ALFRESCO_PASSWORD` is provided            |
|                       |                      | Sourced from Jenkins credential `ALFRESCO_API`.                       |

Alfresco ticket generation by API:
- either from Swagger API explorer `/?urls.primaryName=Authentication%20API#/authentication/createTicket`, 
- either with cURL command:
```bash
curl -X POST  -H "Content-Type: application/json" -d '{"username":"admin","password":"admin"}' "https://alfresco.sample.com/alfresco/s/api/login"
```

## Bootstrap delete-roles

Delete mapped roles from various tools symmetrically as [`create-roles` operation](#bootstrap-create-roles).

![Sequence](docs/bootstrap/delete-roles.png)


See [`--from`](#--from) for JSON loading options

By default, only roles are deleted; to perform a full cleanup, see the [--with-data option](#--with-data)

```bash
ligoj bootstrap delete-roles --project project-a --from conf.json \
--with-data "jenkins" "sonar" \
--argocd-token="$ARGOCD_TOKEN" \
--argocd-user="$ARGOCD_USER" \
--alfresco-endpoint="$ALFRESCO_ENDPOINT" \
--alfresco-user="$ALFRESCO_USER" \
--alfresco-password="$ALFRESCO_PASSWORD" \
--nexus-endpoint="$NEXUS_ENDPOINT" \
--nexus-user="$NEXUS_USER" \
--nexus-password="$NEXUS_PASSWORD" \
--gitlab-endpoint="$GITLAB_ENDPOINT" \
--gitlab-token="$GITLAB_TOKEN" \
--jenkins-home="$JENKINS_HOME" \
--jenkins-endpoint="$JENKINS_ENDPOINT" \
--sonar-endpoint="$SONAR_ENDPOINT" \
--sonar-api-token="$SONAR_API_KEY" \
```

Deleted contents by tools

| Tool           | Content type            | Deletion mode | Only `with-data` |
| -------------- | ----------------------- | ------------- | ---------------- |
| Jenkins        | Folder RBAC Permissions | One by one    |                  |
| Jenkins        | Global RBAC Permissions | One by one    |                  |
| Jenkins        | Folder credentials      | One by one    | ✅                |
| Jenkins        | Global credentials      | One by one    | ✅                |
| Jenkins        | Folders                 | One by one    | ✅                |
| SonarQube      | Groups and RBAC         | One by one    |                  |
| SonarQube      | Projects                | One by one    | ✅                |
| SonarQube      | Templates               | One by one    | ✅                |
| GitLab         | Wrapper project Groups  | Cascade       |                  |
| GitLab         | LDAP project Groups     | One by one    |                  |
| GitLab         | Project Groups          | One by one    | ✅                |
| Sonatype Nexus | Roles                   | Cascade       |                  |
| Sonatype Nexus | Repositories            | One by one    | ✅                |
| Alfresco       | Roles                   | Cascade       |                  |
| Alfresco       | Sites                   | One by one    | ✅                |
| ArgoCD         | Permissions             | One by one    |                  |
| ArgoCD         | Projects                | One by one    | ✅                |


### `--with-data`

Each supported tool can be included (by default) or excluded, as described in [`create-roles` includes/excludes option documentation](#--includes-and---excludes-options). For excluded tools, no role and no data are deleted.

By default, only roles are deleted. To symmetrically delete the created contents, `--with-data` must be set to `*` or a specific list of plugins. 
In this case, all discovered JSON content is considered for deletion, including Jenkins folders, Nexus repositories, etc.
- By default, no data is deleted
- When `--with-data` is set to `*`, all discovered JSON's content for included plugins is considered
- When `--with-data` is set to `plugin1 plugin2`, only these plugins are considered for data deletion, only if these plugins are included

## Bootstrap roundtrip

The purpose of this documentation is only for troubleshooting and understanding the full behavior of bootstrap operations:
- [Bootstrap init](#bootstrap-init) : initial IDP (LDAP, ...), administrative setup. Only executed once.
- [Bootstrap welcome-user](#bootstrap-welcome-user): initial administration user. Each administrator can execute their own base configuration.
- [Bootstrap create-project](#bootstrap-create-project): create a new project in Ligoj and the linked IDP
- [Bootstrap create-roles](#bootstrap-create-roles): permissions, role mapping and containers creation for an existing project
- [Bootstrap delete-roles](#bootstrap-delete-roles): permissions, role mapping and containers deletion from a project
- [Bootstrap delete-project](#bootstrap-delete-project): delete a project from Ligoj and linked IDP

Commands from zero to zero:

```bash
ligoj -V bootstrap init --base-dn="dc=sample,dc=com"
ligoj -V bootstrap welcome-user --id "jdupont" --project "pic-master" --name "PIC Master" --script-custom-attributes '{"uidFonctionnel":"pic-master-script"}' --reader-custom-attributes '{"uidFonctionnel":"pic-master-reader"}' --jenkins-create-node --sonar-create-node --reset-reader-password  
ligoj -V bootstrap create-project --project "project-module1" --name "ProjetNew" --groups "dev" "admin" --parent-project "pic-master" --parent-admin "jdupont" --team-leader jdupont
ligoj -V bootstrap create-roles --project "project-module1" --from "conf/ligoj/sample.conf.json" --excludes gitlab alfresco argocd
ligoj -V bootstrap create-roles --project "project-module1" --from "conf/ligoj/sample.conf.json" --excludes gitlab
ligoj -V bootstrap delete-roles --project "project-module1" --from "conf/ligoj/sample.conf.json" --excludes gitlab
ligoj -V project delete              --id "project-module1" --parent-admin "jdupont" --with-data '*'
ligoj -V project delete              --id "pic-master" --with-data '*'
```

# Ligoj SSL Certificates

This section covers the case of running Ligoj with interaction with HTTPS services using self-signed certificates or issued by internal Certificate Authorities.

For each HTTPS website, run the following command. It requires `keytool` to be available on the host.

```bash
python plugins/ssl.py keycloack.sample.com 443 ./ligoj.jks changeit
```

When successive calls are done, the target TrustStore JKS file contains all aggregated certificates and can be provided to `ligoj-ui` and/or `ligoj-api` containers.

```bash
# Copy the TrustStore file in the mounted Ligoj home directory
cp ./ligoj.jks /var/lib/instance_datas/ligoj/

# Start the container with the TrustStore reference
docker run -e CUSTOM_OPTS='-Djavax.net.ssl.trustStore=/home/ligoj/ligoj.jks' \
```


# Development

Local development uses [`uv`](https://docs.astral.sh/uv/) and the provided [`Makefile`](Makefile).
`uv` creates the virtual environment and installs the exact runtime and dev dependencies declared
in [`pyproject.toml`](pyproject.toml) — no manual `venv` / `pip` steps are required.

```bash
# 1. Install uv — see https://docs.astral.sh/uv/getting-started/installation/
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Create the virtual environment and install all dependencies
make init                     # uv sync

# 3. Run the CLI from the source tree
make run ARGS="--version"     # or: uv run ligoj --version
```

Common tasks (run `make help` to list them all):

| Command       | Description                                    |
| ------------- | ---------------------------------------------- |
| `make init`   | Create the venv and install all dependencies   |
| `make run`    | Run the CLI, e.g. `make run ARGS="info status"`|
| `make format` | Auto-format and apply safe fixes with `ruff`   |
| `make lint`   | Static analysis with `ruff` and `flake8`       |
| `make build`  | Build the sdist and wheel into `dist/`         |
| `make check`  | Validate the built distributions with `twine`  |
| `make clean`  | Remove build artifacts and caches              |

# Releasing

Publishing is fully automated through GitHub Actions using
[PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC, no API token).
See [RELEASE.md](RELEASE.md) for the complete checklist.

| Stage            | Index                                                | Trigger                              | Workflow |
| ---------------- | ---------------------------------------------------- | ------------------------------------ | -------- |
| **Test publish** | [TestPyPI](https://test.pypi.org/project/ligoj-cli/) | Push to the `develop` branch         | [deploy-test.yml](.github/workflows/deploy-test.yml) |
| **Release**      | [PyPI](https://pypi.org/project/ligoj-cli/)          | Publish a GitHub Release (tag `v*`)  | [deploy.yml](.github/workflows/deploy.yml) |

## Test publish (TestPyPI)

Every push to `develop` builds the package, appends a unique `.dev<run-number>` suffix to the
version, and uploads it to TestPyPI. Use it to validate the package end-to-end before a real release.

```bash
git switch develop
git push origin develop
```

Then smoke-test the published build in a throwaway environment:

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ ligoj-cli
ligoj --version
```

## Release (PyPI)

A release is triggered by **publishing a GitHub Release** — pushing a tag alone does **not** publish.

1. Bump `version` in [pyproject.toml](pyproject.toml) following [SemVer](https://semver.org/),
   then commit and land it on `master`.
2. Build and validate locally (optional but recommended):
   ```bash
   make check
   ```
3. Create and publish the release. This creates the `vX.Y.Z` tag and fires
   [deploy.yml](.github/workflows/deploy.yml):
   ```bash
   gh release create vX.Y.Z --target master --generate-notes
   ```
4. Verify on [PyPI](https://pypi.org/project/ligoj-cli/).
