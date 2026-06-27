#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-build-jenkins: register the local Jenkins node.
#
from ligojcli.dev_demo import _common

ARTIFACT = "plugin-build-jenkins"
NODE = "service:build:jenkins:local"


def run(args):
    _common.upsert_node(
        NODE,
        "Jenkins Local (CLI)",
        {
            "service:build:jenkins:url": _common.dev_value(
                args, "jenkins_endpoint", "JENKINS_ENDPOINT", "http://localhost:8085"
            ),
            "service:build:jenkins:user": _common.dev_value(
                args, "jenkins_api_user", "JENKINS_API_USER", "admin"
            ),
            "service:build:jenkins:api-token": _common.dev_value(
                args, "jenkins_api_token", "JENKINS_API_TOKEN", None
            ),
        },
    )
