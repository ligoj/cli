#!/usr/bin/env python
#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import json
import os
import sys

from ligojcli.plugins import (
    alfresco,
    argocd,
    bootstrap,
    build,
    gitlab,
    harbor,
    id,
    jenkins,
    nexus,
    prov,
    sonarqube,
    utils,
)
from ligojcli.plugins import ligoj as ligoj_plugin


def main():
    (parser, subparser_service) = utils.init()
    alfresco.configure(subparser_service)
    argocd.configure(subparser_service)
    bootstrap.configure(subparser_service)
    build.configure(subparser_service)
    gitlab.configure(subparser_service)
    harbor.configure(subparser_service)
    id.configure(subparser_service)
    jenkins.configure(subparser_service)
    ligoj_plugin.configure(subparser_service)
    nexus.configure(subparser_service)
    prov.configure(subparser_service)
    sonarqube.configure(subparser_service)

    (args, output) = utils.configure(parser)

    if args["version"] is True:
        service = "info"
        action = "version"
        operation = None
    else:
        service = args.get("service")
        action = args.get("action")
        operation = args.get("operation")
    if action is None or service is None:
        parser.print_usage()
        return

    ligoj_plugin.parse_remote_args(args)

    result = execute_action(service, action, operation, args)
    if result is False:
        # Ignore output
        return

    if isinstance(result, str):
        result = {"id": result}
    elif result is not None:
        try:
            result = result.json()
        except BaseException:
            try:
                result = {"id": result.text}
            except BaseException:
                pass

    if output == "json":
        try:
            print(json.dumps(result))
        except Exception:
            print("Unable to display result as JSON", result)

    elif output == "text":
        if isinstance(result, str):
            print(result)
        elif result is None or (isinstance(result, dict) and len(result.keys()) == 0):
            print("")
        elif isinstance(result, dict) and len(result.keys()) == 1:
            print(result[list(result.keys())[0]])
        elif isinstance(result, dict):
            for key in result.keys():
                print(result[key])
        else:
            print(result)


def execute_action(service, action, operation, args):
    utils.check_endpoint(utils.not_none(ligoj_plugin.ligoj_endpoint, "endpoint"), "ligoj")
    utils.debug(
        f"[ligoj] Ligoj CLI '{service}/{action}' profile '{utils.ini_profile}', user '{ligoj_plugin.ligoj_api_user}'{'' if ligoj_plugin.ligoj_api_run_as_user is None else (' as ' + ligoj_plugin.ligoj_api_run_as_user)} on endpoint '{ligoj_plugin.ligoj_endpoint}'"
    )

    return (
        ligoj_plugin.execute_action(service, action, operation, args)
        or alfresco.execute_action(service, action, operation, args)
        or argocd.execute_action(service, action, operation, args)
        or bootstrap.execute_action(service, action, operation, args)
        or build.execute_action(service, action, operation, args)
        or gitlab.execute_action(service, action, operation, args)
        or harbor.execute_action(service, action, operation, args)
        or id.execute_action(service, action, operation, args)
        or jenkins.execute_action(service, action, operation, args)
        or nexus.execute_action(service, action, operation, args)
        or prov.execute_action(service, action, operation, args)
        or sonarqube.execute_action(service, action, operation, args)
        or False
    )


def ligoj() -> int:
    """Entry point for the ligoj CLI."""
    try:
        main()
    except ValueError as e:
        utils.error(str(e))
        sys.exit(os.EX_SOFTWARE)
        return os.EX_SOFTWARE
    except SystemExit as e:
        raise e
    except BaseException as e:
        template = "An exception of type {0} occurred. Arguments:\n{1!r}"
        error_message = template.format(type(e).__name__, e.args)
        utils.error(error_message)
        raise e
    return 0


if __name__ == "__main__":
    ligoj()
