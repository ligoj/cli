from ligojcli.ligoj import build_parser
from ligojcli.plugins import utils


def parse(*argv):
    parser = build_parser()
    utils.share_global_options(parser)
    return vars(parser.parse_args(list(argv)))


def test_global_option_after_the_command():
    assert parse("node", "list", "--output", "table")["output"] == "table"


def test_global_option_before_the_command_still_works():
    assert parse("--output", "table", "node", "list")["output"] == "table"


def test_absent_global_option_keeps_its_default():
    args = parse("node", "list")
    assert args["output"] is None and args["debug"] is False and args["profile"] is None


def test_global_options_after_a_nested_command():
    args = parse("dev", "backup", "list", "--debug", "--profile", "other", "-o", "json")
    assert args["debug"] is True and args["profile"] == "other" and args["output"] == "json"


def test_global_option_value_is_not_taken_as_a_positional():
    args = parse("dev", "update", "--check", "--output", "table")
    assert args["output"] == "table" and args["update_service"] == []


def test_command_keeps_its_own_short_flag():
    # 'file get -o' is the output file; the long '--output' stays the global output mode
    args = parse("file", "get", "-o", "copy.txt", "--output", "text")
    assert args["out"] == "copy.txt" and args["output"] == "text"


def test_command_keeps_its_own_option_and_version_is_not_shared():
    assert parse("plugin", "install", "--id", "plugin-vm", "--version", "1.2")["version"] == "1.2"
    assert parse("node", "list", "--output", "text").get("version") is False
