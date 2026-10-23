"""python -m erasebot：fixture-only offline dry-run CLI。"""

import argparse
import json

from .selection import EXIT_CODES, InputError, invalid_result, load_json, select_target


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError("arguments", "arguments", message)


def main(argv=None):
    parser = Parser(description="以 fixture 文字及顏色精確選取目標的離線 dry-run；不控制硬體。", allow_abbrev=False)
    parser.add_argument("--command", required=True, help="UTF-8 command JSON 路徑（相對於目前目錄）")
    parser.add_argument("--scene", required=True, help="UTF-8 scene JSON 路徑（相對於目前目錄）")
    try:
        args = parser.parse_args(argv)
        command = load_json(args.command, "command")
        scene = load_json(args.scene, "scene")
        result = select_target(command, scene)
    except InputError as exc:
        result = invalid_result(exc.stage, [{"path": exc.path, "message": str(exc)}])
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
