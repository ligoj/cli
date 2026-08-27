#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# `dev plugin create <plugin>` — scaffold a brand-new Ligoj plugin in the current directory.
#
# The <plugin> is the full Maven artifact and MUST start with 'plugin-'. Its fragments decide the
# type, mirroring the real plugin naming:
#   * one fragment  -> a SERVICE plugin, e.g. 'plugin-km'          (like plugin-id)
#   * two+ fragments -> a TOOL plugin,   e.g. 'plugin-km-confluence' (like plugin-id-ldap), which
#                       extends the service 'plugin-<first fragment>' via a 'provided' dependency.
#
# The generated project compiles and its (plain JUnit + Vitest) tests give 100% coverage of the
# generated code: a minimal-but-real skeleton modelled on plugin-km / plugin-km-confluence.
#
import concurrent.futures
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET

from colorama import Fore, Style

from ligojcli.plugins import utils

# Versions/coordinates shared by every generated plugin (kept in sync with the real plugins).
_PLUGIN_PARENT_VERSION = "4.3.2"
_PLUGIN_VERSION = "1.0.0-SNAPSHOT"
_GROUP_ID = "org.ligoj.plugin"
_NAME_RE = re.compile(r"^plugin-[a-z0-9]+(-[a-z0-9]+)*$")


def _cap(fragment):
    """Capitalize a name fragment for a Java identifier: 'km' -> 'Km', 'confluence' -> 'Confluence'."""
    return fragment[:1].upper() + fragment[1:]


def _context(artifact, display_name, description):
    """Compute every derived name (packages, classes, keys, paths) for the templates."""
    fragments = artifact[len("plugin-") :].split("-")
    is_tool = len(fragments) > 1
    service = fragments[0]
    plugin_id = "-".join(fragments)  # UI id + webjar path segment, e.g. 'km' or 'km-confluence'
    pkg_last = fragments[-1]  # Java package leaf: the service ('km') or the tool ('confluence')
    port = 5180 + (sum(ord(character) for character in artifact) % 100)

    context = {
        "artifact": artifact,
        "name": display_name,
        "description": description,
        "is_tool": is_tool,
        "service": service,
        "plugin_id": plugin_id,
        "pkg_last": pkg_last,
        "pkg": f"org.ligoj.app.plugin.{pkg_last}",
        "pkg_path": f"org/ligoj/app/plugin/{pkg_last}",
        "webjar_id": plugin_id,
        "vite_port": port,
        "year": 2026,
    }
    if is_tool:
        context.update(
            {
                "resource_class": f"{_cap(pkg_last)}PluginResource",
                "url_suffix": "/".join(fragments[1:]),  # 'confluence' or 'ldap/embedded'
                "key": "service:" + ":".join(fragments),  # 'service:km:confluence'
                "parent_artifact": f"plugin-{service}",
                "parent_pkg": f"org.ligoj.app.plugin.{service}",
                "parent_resource": f"{_cap(service)}Resource",
                "parent_iface": f"{_cap(service)}ServicePlugin",
            }
        )
    else:
        context.update(
            {
                "resource_class": f"{_cap(service)}Resource",
                "iface_class": f"{_cap(service)}ServicePlugin",
                "key": f"service:{service}",
            }
        )
    return context


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def execute(args):
    operation = args.get("operation")
    if operation == "create":
        return _create(args)
    if operation == "build":
        # 'dev plugin build' — run 'npm run build' for each plugin frontend (logic lives in dev.py).
        from ligojcli.plugins import dev

        return dev.dev_build_plugin(args)
    if operation == "renovate":
        return _renovate(args)
    utils.warn(
        "[plugin] missing sub-command; try 'dev plugin create <plugin>', "
        "'dev plugin build' or 'dev plugin renovate'"
    )
    return False


def _create(args):
    artifact = (args.get("plugin") or "").strip()
    if not _NAME_RE.match(artifact):
        raise ValueError(
            f"[plugin] invalid plugin name '{artifact}': must start with 'plugin-' and use "
            "lowercase fragments, e.g. 'plugin-km' (service) or 'plugin-km-confluence' (tool)"
        )

    parent_dir = os.path.abspath(os.path.expanduser(args.get("dir") or os.getcwd()))
    base_dir = os.path.join(parent_dir, artifact)
    if os.path.exists(base_dir):
        raise ValueError(f"[plugin] target directory already exists: {base_dir}")

    fragments = artifact[len("plugin-") :].split("-")
    is_tool = len(fragments) > 1
    kind = "tool" if is_tool else "service"
    default_name = "Ligoj - Plugin " + " - ".join(_cap(fragment) for fragment in fragments)
    default_description = f"{'Tool' if is_tool else 'Service'} plugin '{artifact}' for Ligoj."

    utils.info(f"[plugin] Creating {kind} plugin '{artifact}' in {parent_dir}")
    if is_tool:
        utils.info(f"[plugin] Tool of service 'plugin-{fragments[0]}' (provided dependency)")

    display_name = args.get("name") or _ask("Plugin display name", default_name)
    description = args.get("description") or _ask("Plugin description", default_description)

    context = _context(artifact, display_name, description)
    _generate(context, base_dir)
    _generate_lockfile(base_dir)

    utils.info(f"[plugin] Created {artifact} ({kind}) at {base_dir}")
    utils.info(
        f"[plugin] Next: 'cd {artifact} && mvn verify' (the Maven build compiles, runs the "
        "JUnit + Vitest tests, and builds the Vue UI bundle)"
    )
    return False


def _npm():
    """Locate npm — PATH first, then the newest nvm install (scripts don't source the profile)."""
    npm = shutil.which("npm")
    if npm:
        return npm
    candidates = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/npm")))
    return candidates[-1] if candidates else None


def _generate_lockfile(base_dir):
    """Create ui/package-lock.json — the Maven frontend build runs 'npm ci', which requires it."""
    ui_dir = os.path.join(base_dir, "ui")
    npm = _npm()
    if not npm:
        utils.warn(
            "[plugin] npm not found: run 'cd ui && npm install' to create package-lock.json "
            "(the Maven frontend build's 'npm ci' needs it)"
        )
        return
    utils.info("[plugin] Generating ui/package-lock.json (npm install --package-lock-only) ...")
    env = dict(os.environ, PATH=os.path.dirname(npm) + os.pathsep + os.environ.get("PATH", ""))
    result = subprocess.run(
        [npm, "install", "--package-lock-only", "--no-audit", "--no-fund"],
        cwd=ui_dir,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        utils.warn(
            "[plugin] Could not generate the lockfile; run 'cd ui && npm install' yourself:\n"
            + (result.stderr or "").strip()[-400:]
        )
    else:
        utils.info("[plugin] ui/package-lock.json generated")


def _ask(label, default):
    """Prompt with a default; blank input keeps the default. Falls back to the default without a TTY."""
    try:
        answer = input(f"{label} [{default}]: ").strip()
    except EOFError:
        answer = ""
    return answer or default


# --------------------------------------------------------------------------- #
# File generation
# --------------------------------------------------------------------------- #
def _generate(context, base_dir):
    files = {
        "pom.xml": _pom_xml,
        "README.md": _readme_md,
        "LICENSE": _license,
        ".gitignore": _gitignore,
        ".codeclimate.yml": _codeclimate_yml,
        ".github/workflows/build.yml": _workflow_yml,
        "src/main/resources/csv/node.csv": _node_csv,
        f"src/main/java/{context['pkg_path']}/{context['resource_class']}.java": _resource_java,
        f"src/test/java/{context['pkg_path']}/{context['resource_class']}Test.java": _resource_test_java,
        "ui/package.json": _ui_package_json,
        "ui/vite.config.js": _ui_vite_config,
        "ui/eslint.config.js": _ui_eslint_config,
        "ui/index.html": _ui_index_html,
        "ui/.gitignore": _ui_gitignore,
        "ui/src/index.js": _ui_index_js,
        "ui/src/service.js": _ui_service_js,
        "ui/src/i18n/en.js": _ui_i18n_en_js,
        "ui/src/i18n/fr.js": _ui_i18n_fr_js,
        "ui/src/__tests__/setup.js": _ui_setup_js,
        f"ui/src/__tests__/plugin-{context['plugin_id']}.test.js": _ui_test_js,
    }
    if context["is_tool"]:
        files["src/main/resources/csv/parameter.csv"] = _parameter_csv
    else:
        iface = context["iface_class"]
        files[f"src/main/java/{context['pkg_path']}/{iface}.java"] = _iface_java

    for relative, builder in files.items():
        path = os.path.join(base_dir, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        content = builder(context)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content if content.endswith("\n") else content + "\n")
        utils.debug(f"[plugin]   + {relative}")


_JAVA_HEADER = (
    "/*\n * Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)\n */\n"
)


# --------------------------------------------------------------------------- #
# Maven / docs / config templates
# --------------------------------------------------------------------------- #
def _pom_xml(context):
    dependencies = ""
    if context["is_tool"]:
        parent = context["parent_artifact"]
        lower = _PLUGIN_VERSION
        # Provided dependency on the parent service plugin, with a compatible version range.
        upper = _next_minor(_PLUGIN_VERSION)
        dependencies = f"""
    <dependencies>
        <dependency>
            <groupId>{_GROUP_ID}</groupId>
            <artifactId>{parent}</artifactId>
            <version>[{lower},{upper})</version>
            <scope>provided</scope>
        </dependency>
    </dependencies>
"""
    properties = (
        ""
        if context["is_tool"]
        else (
            "\n    <properties>\n        <sonar.sources>src/main/java</sonar.sources>\n    </properties>\n"
        )
    )
    return f"""<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>org.ligoj.api</groupId>
        <artifactId>plugin-parent</artifactId>
        <version>{_PLUGIN_PARENT_VERSION}</version>
        <relativePath />
    </parent>

    <groupId>{_GROUP_ID}</groupId>
    <artifactId>{context["artifact"]}</artifactId>
    <version>{_PLUGIN_VERSION}</version>
    <packaging>jar</packaging>
    <name>{context["name"]}</name>
    <description>{context["description"]}</description>

    <scm>
        <connection>scm:git:https://github.com/ligoj/{context["artifact"]}</connection>
        <developerConnection>scm:git:https://github.com/ligoj/{context["artifact"]}</developerConnection>
        <url>https://github.com/ligoj/{context["artifact"]}.git</url>
    </scm>
{properties}{dependencies}
    <profiles>
        <profile>
            <id>github</id>
            <distributionManagement>
                <repository>
                    <id>github-ligoj</id>
                    <url>https://maven.pkg.github.com/ligoj/{context["artifact"]}</url>
                </repository>
            </distributionManagement>
        </profile>
    </profiles>
</project>
"""


def _next_minor(version):
    """'1.0.0-SNAPSHOT' -> '1.1.0' (upper bound of the parent version range)."""
    core = version.split("-", 1)[0]
    parts = core.split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    return f"{major}.{minor + 1}.0"


def _readme_md(context):
    artifact = context["artifact"]
    escaped = artifact.replace("-", "--")
    project = f"org.ligoj.plugin%3A{artifact}"
    relation = ""
    if context["is_tool"]:
        relation = (
            f"\nImplementation of the [plugin-{context['service']}]"
            f"(https://github.com/ligoj/plugin-{context['service']}) service for "
            f"{context['name']}.\n"
        )
    return f"""## :link: {context["name"]} ![Maven Central](https://img.shields.io/maven-central/v/{_GROUP_ID}/{artifact})
{context["description"]}

[![Coverage](https://sonarcloud.io/api/project_badges/measure?project={project}&metric=coverage)](https://sonarcloud.io/dashboard?id={project})
[![Quality Gate](https://sonarcloud.io/api/project_badges/measure?metric=alert_status&project={project})](https://sonarcloud.io/dashboard/index/{project})
[![License](http://img.shields.io/:license-mit-blue.svg)](http://fabdouglas.mit-license.org/)

[Ligoj](https://github.com/ligoj/ligoj) {context["name"]} plugin — `{context["key"]}`.
{relation}
### Build

```bash
cd ui && npm install && npm run build   # builds the Vue UI bundle into src/main/resources
mvn verify                              # compiles, tests (100% coverage) and packages the jar
```

Badge/repository slug: `{escaped}`.
"""


def _license(context):
    return f"""MIT License

Copyright (c) {context["year"]} Ligoj (links)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def _gitignore(context):
    return f"""**/.DS_Store
**/.settings
**/.project
**/target
**/.classpath
**/dependency-reduced-pom.xml
/*.exec
/.idea
src/main/resources/META-INF/resources/webjars/{context["webjar_id"]}/vue/
"""


def _codeclimate_yml(_context):
    return """version: "2"
checks:
  argument-count:
    enabled: false
  similar-code:
    enabled: false
  file-lines:
    enabled: false
  method-count:
    enabled: false
  method-lines:
    enabled: false
  identical-code:
    enabled: false
plugins:
  csslint:
    enabled: true
  markdownlint:
    enabled: true
  eslint:
    enabled: true
"""


def _workflow_yml(context):
    return f"""name: SonarCloud
on:
  push:
    branches:
      - master
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  build:
    name: Build and analyze
    runs-on: ubuntu-latest
    steps:
      - uses: s4u/setup-maven-action@ba34de01b7f4ba2ab8e2860df8993a29f4477056
        with:
          checkout-fetch-depth: 0
          java-version: 25
          java-distribution: 'corretto'
          cache-path-add: ~/.sonar/cache
          cache-prefix: ${{{{ runner.os }}}}-sonar
          maven-version: 3.9.16
      - name: maven-settings-xml-action
        uses: marcelrgberger/maven-settings-xml-action@acf2b8d12d81cd9119fe2a6175096ad6d1c645c2
        with:
          repositories: '[
                  {{ "id": "spring-milestone", "url": "https://repo.spring.io/milestone/"}},
                  {{ "id": "oss-sonatype", "url": "https://oss.sonatype.org/service/local/repositories/releases/content/"}}
                ]'
          plugin_repositories: '[{{ "id": "spring-milestone", "url": "https://repo.spring.io/milestone/"}}]'
          active_profiles: '["github"]'
      - name: Extract Maven project version
        run: |
          echo "RELEASE_VERSION=$(mvn help:evaluate -Dexpression=project.version -q -DforceStdout)" >> $GITHUB_ENV
      - name: Build and analyze
        env:
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}
          SONAR_TOKEN: ${{{{ secrets.SONAR_TOKEN }}}}
        run: mvn -B -e -V clean package jacoco:report org.sonarsource.scanner.maven:sonar-maven-plugin:sonar
          -Dmaven.test.redirectTestOutputToFile=false
          -Djava.net.preferIPv4Stack=true
          -Dsurefire.useFile=false
          -DbuildVersion=${{{{ env.RELEASE_VERSION }}}}
          -Dskip-sonarsource-repo=true
          -Pjacoco -Djacoco.includes="{context["pkg"]}.*"
          -Dsonar.projectKey="{_GROUP_ID}:{context["artifact"]}"
          -Dsonar.javascript.exclusions="node_modules,dist"
          -Dsonar.host.url="https://sonarcloud.io"
          -Dsonar.organization=ligoj-github
          -Dmaven.javadoc.skip=true
          -Dmaven.ut.reuseForks=true -Dmaven.it.reuseForks=false
          -Djava.awt.headless=true
"""


def _node_csv(context):
    header = "id;name;refined.id;mode;uiClasses;tag;tagUiClasses"
    if context["is_tool"]:
        row = f"{context['key']};{context['name']};service:{context['service']};LINK;;;"
    else:
        row = f"{context['key']};{context['name']};;ALL;fa fa-cube;functional;fa fa-suitcase"
    return f"{header}\n{row}\n"


def _parameter_csv(context):
    key = context["key"]
    header = (
        "id;owner.id;data;mandatory;type;mode;secured;defaultValue;"
        "availableForSubscription;availableForNode"
    )
    row = f"{key}:url;{key};;TRUE;TEXT;;;;FALSE;"
    return f"{header}\n{row}\n"


# --------------------------------------------------------------------------- #
# Java templates
# --------------------------------------------------------------------------- #
def _resource_java(context):
    if context["is_tool"]:
        return (
            _JAVA_HEADER
            + f"""package {context["pkg"]};

import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;

import org.ligoj.app.plugin.{context["service"]}.{context["parent_resource"]};
import org.ligoj.app.plugin.{context["service"]}.{context["parent_iface"]};
import org.ligoj.app.resource.plugin.AbstractToolPluginResource;
import org.springframework.stereotype.Component;

/**
 * {context["name"]} tool resource.
 */
@Path({context["resource_class"]}.URL)
@Component
@Produces(MediaType.APPLICATION_JSON)
public class {context["resource_class"]} extends AbstractToolPluginResource implements {context["parent_iface"]} {{

\t/**
\t * Plug-in URL path.
\t */
\tpublic static final String URL = {context["parent_resource"]}.SERVICE_URL + "/{context["url_suffix"]}";

\t/**
\t * Plug-in key.
\t */
\tpublic static final String KEY = URL.replace('/', ':').substring(1);

\t/**
\t * Endpoint URL parameter.
\t */
\tpublic static final String PARAMETER_URL = KEY + ":url";

\t@Override
\tpublic String getKey() {{
\t\treturn KEY;
\t}}
}}
"""
        )
    return (
        _JAVA_HEADER
        + f"""package {context["pkg"]};

import org.ligoj.app.resource.plugin.AbstractServicePlugin;
import org.springframework.stereotype.Component;

/**
 * The {context["name"]} service.
 */
@Component
public class {context["resource_class"]} extends AbstractServicePlugin {{

\t/**
\t * Plug-in URL path.
\t */
\tpublic static final String SERVICE_URL = BASE_URL + "/{context["service"]}";

\t/**
\t * Plug-in key.
\t */
\tpublic static final String SERVICE_KEY = SERVICE_URL.replace('/', ':').substring(1);

\t@Override
\tpublic String getKey() {{
\t\treturn SERVICE_KEY;
\t}}
}}
"""
    )


def _iface_java(context):
    return (
        _JAVA_HEADER
        + f"""package {context["pkg"]};

import org.ligoj.app.api.ServicePlugin;

/**
 * Features of {context["name"]} implementations.
 */
public interface {context["iface_class"]} extends ServicePlugin {{

\t// Nothing to add yet
}}
"""
    )


def _resource_test_java(context):
    return (
        _JAVA_HEADER
        + f"""package {context["pkg"]};

import org.junit.jupiter.api.Assertions;
import org.junit.jupiter.api.Test;

/**
 * Test class of {{@link {context["resource_class"]}}}.
 */
class {context["resource_class"]}Test {{

\t@Test
\tvoid getKey() {{
\t\tAssertions.assertEquals("{context["key"]}", new {context["resource_class"]}().getKey());
\t}}
}}
"""
    )


# --------------------------------------------------------------------------- #
# Vue UI templates (modelled on plugin-km / plugin-km-confluence)
# --------------------------------------------------------------------------- #
def _ui_package_json(context):
    return f"""{{
  "name": "ligoj-{context["artifact"]}",
  "version": "0.1.0",
  "description": "{context["description"]}",
  "private": true,
  "type": "module",
  "license": "MIT",
  "scripts": {{
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "lint:fix": "eslint . --fix",
    "test": "vitest run",
    "test:watch": "vitest"
  }},
  "devDependencies": {{
    "@eslint/js": "^10.0.1",
    "@vitejs/plugin-vue": "6.0.7",
    "@vue/test-utils": "^2.4.10",
    "eslint": "^10.3.0",
    "eslint-plugin-vue": "^10.9.1",
    "globals": "^17.0.0",
    "jsdom": "^28.1.0",
    "pinia": "^3.0.4",
    "vite": "^8.0.16",
    "vitest": "^4.1.7",
    "vue": "^3.5.34",
    "vue-router": "^5.0.6"
  }}
}}
"""


def _ui_vite_config(context):
    return f"""import {{ defineConfig }} from "vite"
import vue from "@vitejs/plugin-vue"
import {{ resolve }} from "path"

// The Ligoj UI host is resolved as a sibling checkout (../../../ligoj); adjust if your layout differs.
const HOST_SRC = resolve(__dirname, "../../../ligoj/app-ui/src/main/webapp/src")

export default defineConfig({{
  plugins: [vue()],
  resolve: {{
    alias: {{
      "@ligoj/host": resolve(HOST_SRC, "host.js"),
      "@": HOST_SRC,
    }},
    dedupe: ["vue", "pinia", "vue-router", "vuetify"],
  }},
  build: {{
    lib: {{ entry: resolve(__dirname, "src/index.js"), formats: ["es"], fileName: () => "index.js" }},
    outDir: resolve(__dirname, "../src/main/resources/META-INF/resources/webjars/{context["webjar_id"]}/vue"),
    emptyOutDir: true,
    rollupOptions: {{
      external: ["vue", "vue-router", "pinia", "vuetify", "@ligoj/host"],
      output: {{ assetFileNames: "index.[ext]" }},
    }},
  }},
  server: {{
    port: {context["vite_port"]},
    proxy: {{
      "/rest": {{ target: "http://localhost:8080", changeOrigin: true }},
      "/webjars": {{ target: "http://localhost:8080", changeOrigin: true }},
    }},
  }},
  test: {{
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/__tests__/setup.js"],
    exclude: ["node_modules/**", "dist/**"],
    css: false,
    server: {{ deps: {{ inline: ["vuetify"] }} }},
    coverage: {{ include: ["src/index.js", "src/service.js"] }},
  }},
}})
"""


def _ui_eslint_config(context):
    ignore = f"../src/main/resources/META-INF/resources/webjars/{context['webjar_id']}/vue/**"
    return f"""import js from "@eslint/js"
import pluginVue from "eslint-plugin-vue"
import globals from "globals"

export default [
  {{ ignores: ["node_modules/**", "{ignore}"] }},
  js.configs.recommended,
  ...pluginVue.configs["flat/essential"],
  {{
    files: ["**/*.{{js,mjs,cjs,vue}}"],
    languageOptions: {{ ecmaVersion: "latest", sourceType: "module", globals: {{ ...globals.browser, ...globals.node }} }},
    rules: {{
      "vue/multi-word-component-names": "off",
      "vue/valid-v-slot": ["error", {{ allowModifiers: true }}],
      "no-unused-vars": ["warn", {{ argsIgnorePattern: "^_" }}],
    }},
  }},
]
"""


def _ui_index_html(context):
    return (
        f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{context["artifact"]} dev</title>'
        f'</head><body><div id="app">{context["artifact"]}</div></body></html>\n'
    )


def _ui_gitignore(_context):
    return "node_modules\ndist\n.vite\n*.log\n.DS_Store\n"


def _ui_index_js(context):
    if context["is_tool"]:
        return f"""/*
 * Plugin "{context["plugin_id"]}" — {context["name"]} (tool-level, `{context["key"]}`).
 *
 * Augments the parent plugin "{context["service"]}" via i18n labels + subscription-row features
 * (a link to the configured endpoint), merged in through the parent's delegation.
 */
import {{ useI18nStore }} from '@ligoj/host'
import enMessages from './i18n/en.js'
import frMessages from './i18n/fr.js'
import service from './service.js'

const features = {{
  renderFeatures: service.renderFeatures,
}}

export default {{
  id: '{context["plugin_id"]}',
  label: '{context["name"]}',
  requires: ['{context["service"]}'],
  install() {{
    const i18n = useI18nStore()
    i18n.merge(enMessages, 'en')
    i18n.merge(frMessages, 'fr')
  }},
  feature(action, ...args) {{
    const fn = features[action]
    if (!fn) throw new Error(`Plugin "{context["plugin_id"]}" has no feature "${{action}}"`)
    return fn(...args)
  }},
  service,
  meta: {{ icon: 'mdi-tools', color: 'indigo-darken-1' }},
}}

export {{ service }}
"""
    return f"""/*
 * Plugin "{context["plugin_id"]}" — {context["name"]} (service-level, `{context["key"]}`).
 *
 * Parent of the {context["plugin_id"]}-<tool> plugins. Ships generic i18n and delegates the
 * subscription-row hooks to the registered tool sub-plugin.
 */
import {{ useI18nStore }} from '@ligoj/host'
import enMessages from './i18n/en.js'
import frMessages from './i18n/fr.js'
import service from './service.js'

const features = {{
  renderFeatures: service.renderFeatures,
  renderDetailsKey: service.renderDetailsKey,
}}

export default {{
  id: '{context["plugin_id"]}',
  label: '{context["name"]}',
  install() {{
    const i18n = useI18nStore()
    i18n.merge(enMessages, 'en')
    i18n.merge(frMessages, 'fr')
  }},
  feature(action, ...args) {{
    const fn = features[action]
    if (!fn) throw new Error(`Plugin "{context["plugin_id"]}" has no feature "${{action}}"`)
    return fn(...args)
  }},
  service,
  meta: {{ icon: 'mdi-cube-outline', color: 'blue-grey-darken-1' }},
}}

export {{ service }}
"""


def _ui_service_js(context):
    if context["is_tool"]:
        return f"""/*
 * Service layer for plugin "{context["plugin_id"]}" (tool-level).
 *
 * The parent plugin "{context["service"]}" delegates the subscription-row hooks here. Kept free of
 * Vue SFC imports so it is straightforward to unit-test.
 */
import {{ renderServiceLink, useI18nStore }} from '@ligoj/host'

const PARAM_URL = '{context["key"]}:url'

export function renderFeatures(subscription) {{
  const url = subscription?.parameters?.[PARAM_URL]
  if (!url) return []
  const {{ t }} = useI18nStore()
  return [renderServiceLink({{ icon: 'mdi-open-in-new', href: url, title: t('{context["key"]}') }})]
}}

export default {{ renderFeatures }}
"""
    return f"""/*
 * Service layer for plugin "{context["plugin_id"]}" (service-level).
 *
 * Ships the parent→child delegation of the subscription-row hooks to the
 * {context["plugin_id"]}-<tool> sub-plugin, resolved via `subPluginIdFor`.
 */
import {{ toolPluginId, delegateFeature }} from '@ligoj/host'

/** `{context["key"]}:<tool>:1` → `{context["plugin_id"]}-<tool>`; null when no tool segment. */
export const subPluginIdFor = toolPluginId

/** Delegate `action` to the {context["plugin_id"]}-<tool> sub-plugin; degrades to [] on any failure. */
export const delegateToToolPlugin = (subscription, action) =>
  delegateFeature(subscription, action, '{context["plugin_id"]}')

const service = {{
  subPluginIdFor,
  delegateToToolPlugin,
  renderFeatures: (subscription) => delegateToToolPlugin(subscription, 'renderFeatures'),
  renderDetailsKey: (subscription) => delegateToToolPlugin(subscription, 'renderDetailsKey'),
}}

export default service
"""


def _ui_i18n_en_js(context):
    if context["is_tool"]:
        return f"""// English labels for the tool plugin "{context["plugin_id"]}".
export default {{
  '{context["key"]}': '{context["name"]}',
  '{context["key"]}:url': 'URL',
}}
"""
    return f"""// Generic English labels for the service plugin "{context["plugin_id"]}".
export default {{
  '{context["key"]}': '{context["name"]}',
}}
"""


def _ui_i18n_fr_js(context):
    if context["is_tool"]:
        return f"""// Libellés français du plugin outil "{context["plugin_id"]}". Voir en.js.
export default {{
  '{context["key"]}': '{context["name"]}',
  '{context["key"]}:url': 'URL',
}}
"""
    return f"""// Libellés français génériques du plugin service "{context["plugin_id"]}". Voir en.js.
export default {{
  '{context["key"]}': '{context["name"]}',
}}
"""


def _ui_setup_js(_context):
    return """import { vi, beforeEach } from "vitest"
globalThis.fetch = vi.fn()
const storage = new Map()
Object.defineProperty(globalThis, "localStorage", {
  value: {
    getItem: (k) => (storage.has(k) ? storage.get(k) : null),
    setItem: (k, v) => { storage.set(k, String(v)) },
    removeItem: (k) => { storage.delete(k) },
    clear: () => { storage.clear() },
  },
  writable: true,
})
beforeEach(() => { storage.clear() })
"""


def _ui_test_js(context):
    plugin_id = context["plugin_id"]
    if context["is_tool"]:
        return f"""import {{ describe, it, expect, vi }} from 'vitest'

// Mock the host so the test is self-contained (no ligoj checkout needed) and fully deterministic.
vi.mock('@ligoj/host', () => ({{
  useI18nStore: () => ({{ merge: () => {{}}, t: (key) => key }}),
  renderServiceLink: (options) => ({{ type: 'a', props: options }}),
}}))

import def, {{ service }} from '../index.js'

describe('plugin-{plugin_id} (tool)', () => {{
  it('exposes the tool manifest', () => {{
    expect(def.id).toBe('{plugin_id}')
    expect(def.requires).toEqual(['{context["service"]}'])
    expect(def.meta).toMatchObject({{ icon: expect.any(String), color: expect.any(String) }})
  }})

  it('install() merges i18n without throwing', () => {{
    expect(() => def.install()).not.toThrow()
  }})

  it('feature() dispatches and rejects unknown actions', () => {{
    expect(def.feature('renderFeatures', {{ parameters: {{}} }})).toEqual([])
    expect(() => def.feature('nope')).toThrow(/no feature "nope"/)
  }})

  it('renderFeatures returns a link only when the URL is configured', () => {{
    expect(service.renderFeatures({{ parameters: {{}} }})).toEqual([])
    const out = service.renderFeatures({{ parameters: {{ '{context["key"]}:url': 'https://example.org' }} }})
    expect(out).toHaveLength(1)
    expect(out[0].props.href).toBe('https://example.org')
  }})
}})
"""
    return f"""import {{ describe, it, expect, vi }} from 'vitest'

// Mock the host so the test is self-contained (no ligoj checkout needed) and fully deterministic.
const registered = {{}}
vi.mock('@ligoj/host', () => ({{
  useI18nStore: () => ({{ merge: () => {{}}, t: (key) => key }}),
  toolPluginId: (subscription) => {{
    const parts = subscription?.node?.id?.split(':')
    return parts && parts[2] ? `{plugin_id}-${{parts[2]}}` : null
  }},
  delegateFeature: (subscription, action) => registered[action] ?? [],
}}))

import def, {{ service }} from '../index.js'
import {{ subPluginIdFor }} from '../service.js'

describe('plugin-{plugin_id} (service)', () => {{
  it('exposes the service manifest (no requires)', () => {{
    expect(def.id).toBe('{plugin_id}')
    expect(def.requires).toBeUndefined()
    expect(def.meta).toMatchObject({{ icon: expect.any(String), color: expect.any(String) }})
  }})

  it('install() merges i18n without throwing', () => {{
    expect(() => def.install()).not.toThrow()
  }})

  it('feature() dispatches and rejects unknown actions', () => {{
    expect(def.feature('renderFeatures', {{ parameters: {{}} }})).toEqual([])
    expect(def.feature('renderDetailsKey', {{ parameters: {{}} }})).toEqual([])
    expect(() => def.feature('nope')).toThrow(/no feature "nope"/)
  }})

  it('subPluginIdFor maps a tool node → {plugin_id}-<tool>', () => {{
    expect(subPluginIdFor({{ node: {{ id: '{context["key"]}:demo:1' }} }})).toBe('{plugin_id}-demo')
    expect(subPluginIdFor({{ node: {{ id: '{context["key"]}' }} }})).toBeNull()
  }})

  it('delegateToToolPlugin forwards to the host', () => {{
    expect(service.delegateToToolPlugin({{}}, 'renderFeatures')).toEqual([])
  }})
}})
"""


# --------------------------------------------------------------------------- #
# `dev plugin renovate [<plugin>]` — bump plugin-parent + align npm deps with the host
# --------------------------------------------------------------------------- #
# Ported from commands/release.sh (the 'renovate' / 'renovate-all' modes), but scoped to just editing
# the files: it updates pom.xml (the org.ligoj.api:plugin-parent version), package.json (re-pins the
# npm dependency constraints shared with the host UI) and package-lock.json (regenerated from
# package.json). Unlike release.sh it does NOT commit — the edits are left in the working tree for
# review. Targets the current directory, a named plugin, or every plugin under LIGOJ_PLUGINS_DIR.
_HOST_PACKAGE_JSON = "~/git/ligoj/app-ui/src/main/webapp/package.json"
_PLUGIN_PARENT_COORDS = ("org.ligoj.api", "plugin-parent")
_LIGOJ_API_PARENT = (
    "org/ligoj/api",
    "parent",
)  # grandparent whose latest local release is the target
_NPM_SECTIONS = ("optionalDependencies", "peerDependencies", "devDependencies", "dependencies")
_SECTION_RE = re.compile(r'"(?:optional|peer|dev)?[Dd]ependencies"\s*:\s*\{')
_ENTRY_RE = re.compile(r'^(\s*)"([^"]+)"(\s*:\s*)"([^"]*)"(\s*,?\s*)$')


def _version_key(version):
    """A sortable key for a dotted version ('4.3.10' > '4.3.2'); qualifiers are ignored."""
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _maven_local_repo():
    """The Maven local repository: settings.xml <localRepository> override, else ~/.m2/repository."""
    settings = os.path.expanduser("~/.m2/settings.xml")
    try:
        node = ET.parse(settings).getroot().find("{*}localRepository")
        if node is not None and (node.text or "").strip():
            return os.path.expanduser(node.text.strip())
    except (OSError, ET.ParseError):
        pass
    return os.path.expanduser("~/.m2/repository")


def _latest_local_release(group_path, artifact_id):
    """Highest released (N.N.N, non-SNAPSHOT, with a published .pom) version in the local repo."""
    base = os.path.join(_maven_local_repo(), group_path, artifact_id)
    if not os.path.isdir(base):
        return None
    releases = []
    for version in os.listdir(base):
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            continue
        if os.path.isfile(os.path.join(base, version, f"{artifact_id}-{version}.pom")):
            releases.append(version)
    return max(releases, key=_version_key) if releases else None


def _pom_parent_field(pom, field):
    """A field of a pom's <parent> block, namespace-agnostic (or '' when absent)."""
    try:
        parent = ET.parse(pom).getroot().find("{*}parent")
    except (OSError, ET.ParseError):
        return ""
    if parent is None:
        return ""
    node = parent.find(f"{{*}}{field}")
    return (node.text or "").strip() if node is not None else ""


def _is_plugin(repo):
    """True when repo/pom.xml is an org.ligoj.api:plugin-parent project (a real Ligoj plugin)."""
    pom = os.path.join(repo, "pom.xml")
    if not os.path.isfile(pom):
        return False
    coords = (_pom_parent_field(pom, "groupId"), _pom_parent_field(pom, "artifactId"))
    return coords == _PLUGIN_PARENT_COORDS


def _renovate_parent(repo, target):
    """Bump the org.ligoj.api:plugin-parent <version> in repo/pom.xml to target.

    Returns (status, fragment): status in changed/skip, fragment a short human summary (or None when
    there is nothing worth saying, e.g. already at the target). Silent on purpose — with several
    plugins renovated in parallel the caller owns the rendering.
    """
    pom = os.path.join(repo, "pom.xml")
    current = _pom_parent_field(pom, "version")
    if not target:
        return "skip", "parent: no target version"
    if current == target:
        return "skip", None
    if current and _version_key(current) > _version_key(target):
        return "skip", f"parent {current} kept (newer than {target})"

    with open(pom, encoding="utf-8") as handle:
        text = handle.read()

    def _bump(match):
        return re.sub(
            r"(<version>)[^<]*(</version>)", rf"\g<1>{target}\g<2>", match.group(0), count=1
        )

    updated = re.sub(r"<parent>.*?</parent>", _bump, text, count=1, flags=re.DOTALL)
    if updated == text:
        return "skip", "parent: <parent><version> not found"
    with open(pom, "w", encoding="utf-8") as handle:
        handle.write(updated)
    return "changed", f"parent {current or '?'}→{target}"


def _host_dependency_map(host):
    """Merge the host package.json's dependency sections into one {name: constraint} ('dependencies' wins)."""
    with open(host, encoding="utf-8") as handle:
        data = json.load(handle)
    merged = {}
    for section in _NPM_SECTIONS:
        merged.update(data.get(section) or {})
    return merged


def _repin_package_json(text, host_map):
    """Re-pin shared dependency constraints to the host's, line-by-line (formatting preserved)."""
    out, changes, in_section = [], [], False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\n")
        if not in_section and _SECTION_RE.search(body):
            in_section = "}" not in body
            out.append(line)
            continue
        if in_section and re.match(r"^\s*\}", body):
            in_section = False
            out.append(line)
            continue
        match = _ENTRY_RE.match(body) if in_section else None
        if match and match.group(2) in host_map:
            name, current, wanted = match.group(2), match.group(4), host_map[match.group(2)]
            if current != wanted:
                newline = "\n" if line.endswith("\n") else ""
                out.append(
                    f'{match.group(1)}"{name}"{match.group(3)}"{wanted}"{match.group(5)}{newline}'
                )
                changes.append((name, current, wanted))
                continue
        out.append(line)
    return "".join(out), changes


def _regenerate_lockfile(pkg_dir):
    """Rebuild AND advance package-lock.json from package.json (no node_modules).

    'npm update --package-lock-only' both syncs the lockfile with the (possibly re-pinned)
    package.json and moves every dependency — direct and transitive — to the newest version its
    semver range allows, which is the whole point of a renovate. package.json constraints are not
    touched (no --save). Returns (ok, tail-of-output).
    """
    npm = _npm()
    if not npm:
        return False, "npm not found (set PATH or install Node.js)"
    env = dict(os.environ, PATH=os.path.dirname(npm) + os.pathsep + os.environ.get("PATH", ""))
    result = subprocess.run(
        [npm, "update", "--package-lock-only", "--no-audit", "--no-fund"],
        cwd=pkg_dir,
        capture_output=True,
        text=True,
        env=env,
    )
    tail = "\n".join(((result.stdout or "") + (result.stderr or "")).strip().splitlines()[-3:])
    return result.returncode == 0, tail


def _host_allow_scripts(host):
    """The host package.json's allowScripts map (npm >= 11.19 install-script approvals), or {}."""
    with open(host, encoding="utf-8") as handle:
        return json.load(handle).get("allowScripts") or {}


def _merge_allow_scripts(text, host_allow):
    """Merge the host's allowScripts entries into a plugin package.json text.

    Only ADDS/overwrites the entries the host declares — plugin-specific approvals are kept. When a
    change is needed the file goes through a JSON round-trip (indent 2), so it is reformatted once;
    an already-aligned file is returned untouched. Returns (new_text, changed_entry_count).
    """
    data = json.loads(text)
    current = data.get("allowScripts") or {}
    merged = {**current, **host_allow}
    if merged == current:
        return text, 0
    data["allowScripts"] = merged
    changed = sum(1 for key, value in host_allow.items() if current.get(key) != value)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n", changed


def _renovate_npm(repo, host):
    """Align repo's package.json (deps + allowScripts) with the host, regenerate its lockfile.

    Returns (status, fragments, details): status in changed/skip/error, fragments short summary
    pieces for the one-line report, details the per-dependency change lines (verbose mode only).
    Silent on purpose — with several plugins renovated in parallel the caller owns the rendering.
    """
    relative = next(
        (
            path
            for path in ("ui/package.json", "package.json")
            if os.path.isfile(os.path.join(repo, path))
        ),
        None,
    )
    if not relative:
        return "skip", ["no package.json"], []
    if not os.path.isfile(host):
        return "skip", [f"host package.json not found ({host})"], []

    pkg_path = os.path.join(repo, relative)
    pkg_dir = os.path.dirname(pkg_path)
    host_map = _host_dependency_map(host)
    if not host_map:
        return "skip", ["host declares no dependencies"], []

    with open(pkg_path, encoding="utf-8") as handle:
        original = handle.read()
    updated, changes = _repin_package_json(original, host_map)
    try:
        json.loads(updated)
        updated, approvals = _merge_allow_scripts(updated, _host_allow_scripts(host))
    except json.JSONDecodeError:
        return "error", ["re-pin produced invalid JSON — aborted"], []
    if updated != original:
        with open(pkg_path, "w", encoding="utf-8") as handle:
            handle.write(updated)

    # The lockfile is regenerated on every run (that is what keeps it honest), but 'changed' is
    # reported only when something EFFECTIVELY moved: package.json text, or the lockfile bytes.
    # npm's lockfile output is deterministic, so a re-run minutes later compares byte-identical and
    # the plugin reports up-to-date instead of pretending an update happened.
    lock_path = os.path.join(pkg_dir, "package-lock.json")
    lock_before = None
    if os.path.isfile(lock_path):
        with open(lock_path, "rb") as handle:
            lock_before = handle.read()

    ok, tail = _regenerate_lockfile(pkg_dir)
    if not ok:
        with open(pkg_path, "w", encoding="utf-8") as handle:  # restore our own edit
            handle.write(original)
        return "error", ["npm lockfile regeneration failed — reverted"], [tail]

    lock_changed = True
    if os.path.isfile(lock_path):
        with open(lock_path, "rb") as handle:
            lock_changed = handle.read() != lock_before
    if updated == original and not lock_changed:
        return "skip", [], []

    fragments = []
    if changes:
        fragments.append(f"{len(changes)} dep(s)")
    if approvals:
        fragments.append(f"allowScripts+{approvals}")
    if lock_changed:
        fragments.append("npm update" if fragments else "npm update (lockfile)")
    details = [f"npm: {name} {old} → {new}" for name, old, new in changes]
    if approvals:
        details.append(f"npm: {approvals} allowScripts entry(ies) copied from the host")
    return "changed", fragments, details


def _renovate_repos(args):
    """The plugin repos to renovate: --all, a named/path plugin, or the current directory."""
    from ligojcli.plugins import dev

    plugins_dir = os.path.expanduser(
        args.get("plugins_dir")
        or dev._dev_get(args, "ligoj_plugins_dir", "LIGOJ_PLUGINS_DIR", "~/git/ligoj-plugins")
    )
    if args.get("all"):
        if not os.path.isdir(plugins_dir):
            raise ValueError(f"[plugin] renovate: plugins dir not found: {plugins_dir}")
        repos = [
            os.path.join(plugins_dir, name)
            for name in sorted(os.listdir(plugins_dir))
            if _is_plugin(os.path.join(plugins_dir, name))
        ]
        if not repos:
            raise ValueError(f"[plugin] renovate: no Ligoj plugins under {plugins_dir}")
        return repos

    plugin = (args.get("plugin") or "").strip()
    if plugin:
        candidate = os.path.expanduser(plugin)
        repo = candidate if os.path.isdir(candidate) else os.path.join(plugins_dir, plugin)
        if not _is_plugin(repo):
            raise ValueError(
                f"[plugin] renovate: '{plugin}' is not a Ligoj plugin "
                f"(no org.ligoj.api:plugin-parent pom.xml at {repo})"
            )
        return [repo]

    cwd = os.getcwd()
    if not _is_plugin(cwd):
        raise ValueError(
            "[plugin] renovate: current directory is not a Ligoj plugin "
            "(no org.ligoj.api:plugin-parent pom.xml); pass <plugin> or --all"
        )
    return [cwd]


# Status glyphs of the per-plugin report line (matching the dev status/start rendering style).
# Per-status rendering: plain ASCII glyphs with --no-color, emoji + colorama colors otherwise
# (same gate as every other colored output, utils.no_color).
_RENOVATE_ICONS = {"changed": "✓", "skip": "↷", "error": "✗"}
_RENOVATE_EMOJI = {"changed": "✅", "skip": "💤", "error": "❌"}
_RENOVATE_COLORS = {"changed": Fore.GREEN, "skip": Fore.CYAN, "error": Fore.RED}


def _status_icon(status):
    return _RENOVATE_ICONS[status] if utils.no_color else _RENOVATE_EMOJI[status]


def _paint(text, color):
    return text if utils.no_color else f"{color}{text}{Style.RESET_ALL}"


def _renovate_repo(repo, target, host):
    """Renovate ONE plugin (parent bump + npm alignment); returns the per-plugin result record."""
    name = os.path.basename(os.path.abspath(repo))
    try:
        parent_status, parent_fragment = _renovate_parent(repo, target)
        npm_status, npm_fragments, details = _renovate_npm(repo, host)
    except (OSError, ValueError) as error:
        return {"name": name, "status": "error", "summary": str(error)[:160], "details": []}
    statuses = {parent_status, npm_status}
    status = "error" if "error" in statuses else "changed" if "changed" in statuses else "skip"
    fragments = [fragment for fragment in (parent_fragment, *npm_fragments) if fragment]
    return {
        "name": name,
        "status": status,
        "summary": " · ".join(fragments) or "up-to-date",
        "details": details,
    }


def _parallel_renovate(repos, target, host, jobs):
    """Renovate repos with `jobs` workers; each plugin gets exactly ONE line in the output.

    While in flight a plugin shows in a small live footer (at most `jobs` rows, rewritten in
    place); on completion its footer row is replaced by the plugin's permanent result line, which
    then scrolls away normally. Keeping the live region no taller than the worker count is what
    makes the rendering reliable: one row per PLUGIN (dozens) exceeds the terminal height, and once
    a block scrolls, cursor-up cannot reach back above the screen top — every redraw then appends a
    fresh copy of the whole block instead of updating it. Piped output simply prints each plugin's
    final line as it completes. Workers stay silent (the _renovate_* helpers return instead of
    logging), so parallel runs cannot interleave their output.
    """
    from ligojcli.plugins import dev

    labels = [os.path.basename(os.path.abspath(repo)) for repo in repos]
    width = max(len(label) for label in labels)
    tty = dev._live()
    total = len(repos)
    running = []  # labels currently in flight, in start order (the live footer)
    results = {}
    state = {"footer": 0, "done": 0}  # rows currently on screen below the permanent lines
    lock = threading.Lock()

    def _final_line(label, columns=None):
        result = results[label]
        status = result["status"]
        summary = result["summary"]
        if columns:  # clip the PLAIN text; color codes added after so the slice cannot cut them
            summary = summary[: max(10, columns - width - 8)]
        name = _paint(label.ljust(width), Style.BRIGHT)
        return (
            f"  {name}  {_status_icon(status)} {_paint(summary, _RENOVATE_COLORS[status])}".rstrip()
        )

    def _redraw(final_label=None):
        # Clip to the terminal width: a wrapped line occupies two rows and desyncs the cursor-up
        # arithmetic just like an over-tall block would.
        columns = max(40, shutil.get_terminal_size().columns)
        rows = state["footer"]
        if rows:
            sys.stdout.write(f"\x1b[{rows}A")
        written = 0
        if final_label is not None:
            sys.stdout.write("\r\x1b[K" + _final_line(final_label, columns) + "\n")
            written += 1
        spinner = "…" if utils.no_color else "⏳"
        for label in running:
            name = _paint(label.ljust(width), Style.BRIGHT)
            activity = _paint(f"renovating ({state['done']}/{total} done)", Fore.YELLOW)
            sys.stdout.write(f"\r\x1b[K  {name}  {spinner} {activity}\n")
            written += 1
        leftover = rows - written  # the previous footer was taller: blank what remains of it
        for _ in range(max(0, leftover)):
            sys.stdout.write("\r\x1b[K\n")
        if leftover > 0:
            sys.stdout.write(f"\x1b[{leftover}A")
        state["footer"] = len(running)
        sys.stdout.flush()

    def work(repo, label):
        with lock:
            running.append(label)
            if tty:
                _redraw()
        result = _renovate_repo(repo, target, host)
        with lock:
            running.remove(label)
            results[label] = result
            state["done"] += 1
            if tty:
                _redraw(final_label=label)
            else:
                print(_final_line(label))

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for future in [pool.submit(work, repo, label) for repo, label in zip(repos, labels)]:
            future.result()
    return [results[label] for label in labels]


def _renovate(args):
    host = os.path.expanduser(
        args.get("host_package_json")
        or os.environ.get("LIGOJ_HOST_PACKAGE_JSON")
        or _HOST_PACKAGE_JSON
    )
    target = args.get("parent_version") or _latest_local_release(*_LIGOJ_API_PARENT)
    repos = _renovate_repos(args)
    jobs = max(1, int(args.get("jobs") or 3))

    utils.info(f"[plugin] Renovate {len(repos)} plugin(s); host npm referential: {host}")
    utils.info(f"[plugin] plugin-parent target: {target or '(none found — parent bump skipped)'}")
    if len(repos) == 1:
        # Single plugin: keep the verbose per-change report (each dep re-pin on its own line).
        result = _renovate_repo(repos[0], target, host)
        utils.info(f"[plugin] {result['name']}")
        for detail in result["details"]:
            utils.info(f"[plugin]   {detail}")
        log = utils.warn if result["status"] == "error" else utils.info
        log(f"[plugin]   {_status_icon(result['status'])} {result['summary']}")
        results = [result]
    else:
        utils.info(f"[plugin] Renovating with {min(jobs, len(repos))} parallel worker(s) ...")
        results = _parallel_renovate(repos, target, host, jobs)

    failed = [result for result in results if result["status"] == "error"]
    for result in failed:
        for detail in result["details"]:
            utils.warn(f"[plugin] {result['name']}: {detail}")
    changed = sum(1 for result in results if result["status"] == "changed")
    skipped = sum(1 for result in results if result["status"] == "skip")
    utils.info(
        f"[plugin] Renovate complete: {len(results)} analyzed, {changed} updated, "
        f"{skipped} up-to-date, {len(failed)} error(s) (edits left uncommitted for review)"
    )
    return not failed


# --------------------------------------------------------------------------- #
# Help (surfaced on 'dev plugin create -h')
# --------------------------------------------------------------------------- #
HELP = """\
dev plugin create <plugin> — scaffold a new Ligoj plugin in the current directory.

<plugin> is the full Maven artifact and MUST start with 'plugin-'. Its fragments decide the type:
  * one fragment   -> a SERVICE plugin,  e.g. 'plugin-km'            (like plugin-id)
  * two+ fragments -> a TOOL plugin,     e.g. 'plugin-km-confluence' (like plugin-id-ldap), which
                      extends the service 'plugin-<first fragment>' via a 'provided' dependency.

You are prompted for a display name and a description (or pass --name / --description).

What is generated (compiles + 100% test coverage of the generated code):
  * pom.xml            plugin-parent, correct coordinates; a tool adds the provided parent-service dep
  * Java               the ServicePlugin/ToolPluginResource skeleton (+ the <Service>ServicePlugin
                       interface for a service), package org.ligoj.app.plugin.<fragment>
  * JUnit test         plain JUnit 5, asserts getKey() -> full coverage
  * Vue UI (ui/)       index.js + service.js (host integration), i18n en/fr, package.json, vite.config,
                       eslint, and a Vitest test mocking @ligoj/host
  * resources          csv/node.csv (+ csv/parameter.csv for a tool)
  * project files      README.md, LICENSE (MIT), .gitignore, .codeclimate.yml, GitHub SonarCloud workflow

Options:
  --name NAME          Display name (<name> in pom.xml)         (default: derived; prompted if omitted)
  --description TEXT    One-line description                    (default: derived; prompted if omitted)
  --dir DIR            Parent directory to create the plugin in (default: current directory)

Example:
  ligoj dev plugin create plugin-km-confluence --name "Ligoj - Plugin KM - Confluence"

After creation: build the UI bundle ('cd <plugin>/ui && npm install && npm run build'), then
'mvn -f <plugin> verify'. The Vitest and vite config expect the Ligoj UI host at '../../../ligoj'.
"""


HELP_RENOVATE = """\
dev plugin renovate [<plugin>] — update a plugin's pom.xml, package.json and package-lock.json.

Ported from commands/release.sh (its 'renovate' mode), scoped to editing the files (it does NOT
commit — the edits are left in the working tree for you to review and commit):
  * pom.xml           bump the org.ligoj.api:plugin-parent <version> to the target (see below). A
                      current version newer than the target is left alone.
  * package.json      re-pin the npm dependency constraints that are ALSO declared by the host UI to
                      the host's versions (only shared deps; none added/removed; scripts untouched),
                      and merge the host's allowScripts entries in (npm >= 11.19 install-script
                      approvals, e.g. fsevents — plugin-specific approvals are kept).
  * package-lock.json regenerated AND advanced via 'npm update --package-lock-only': every
                      dependency (direct + transitive) moves to the newest version its semver range
                      allows, and the lockfile stays in sync with package.json for 'npm ci'.
                      package.json constraints are not touched. A plugin where nothing EFFECTIVELY moved
                      (identical package.json, byte-identical lockfile) reports up-to-date, so a
                      re-run moments later ends with 'N analyzed, 0 updated, N up-to-date'.

With more than one plugin the work runs in PARALLEL (--jobs workers, default 3) and every plugin
gets exactly ONE output line: while in flight it shows in a small live footer (at most --jobs rows,
'… renovating (n/total done)'), replaced on completion by its permanent result line — changed with a
short summary, up-to-date, or error (failure details printed after the run). On a color terminal the
lines use emoji and colors (⏳ running, ✅ changed, 💤 up-to-date, ❌ error); with --no-color plain
glyphs (… ✓ ↷ ✗). A single plugin keeps the verbose per-dependency report.

Target selection (which plugins):
  <plugin>            a plugin artifact under LIGOJ_PLUGINS_DIR, or a path to a plugin directory
  (omitted)           the current directory (must be an org.ligoj.api:plugin-parent project)
  --all               every Ligoj plugin under LIGOJ_PLUGINS_DIR

Options:
  --parent-version V   plugin-parent target (default: latest local org.ligoj.api:parent release)
  --host-package-json  Host UI package.json (default: LIGOJ_HOST_PACKAGE_JSON or
                       ~/git/ligoj/app-ui/src/main/webapp/package.json)
  --plugins-dir DIR    Plugins root (default: ~/git/ligoj-plugins, LIGOJ_PLUGINS_DIR)
  --jobs N / -j N      Plugins renovated in parallel (default: 3)

Examples:
  ligoj dev plugin renovate                 # renovate the plugin in the current directory
  ligoj dev plugin renovate plugin-km       # a specific plugin under LIGOJ_PLUGINS_DIR
  ligoj dev plugin renovate --all           # every plugin under LIGOJ_PLUGINS_DIR
"""
