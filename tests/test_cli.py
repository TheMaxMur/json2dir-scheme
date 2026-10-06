#!/usr/bin/env python3
"""Black-box CLI tests. Optional JSON2DIR_REFERENCE enables Rust parity tests."""
# SPDX-License-Identifier: ISC

import json
import os
from pathlib import Path
import random
import shutil
import stat
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parent.parent
COMMAND = os.environ.get("JSON2DIR", str(PROJECT / "json2dir"))
REFERENCE = os.environ.get("JSON2DIR_REFERENCE")


def run(command, data, cwd, args=(), mask=0o022):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return subprocess.run(
        [command, *args], input=data, cwd=cwd, capture_output=True,
        umask=mask, timeout=15,
    )


def snapshot(root):
    result = {}
    for entry in sorted(root.iterdir()):
        mode = entry.lstat().st_mode
        if stat.S_ISLNK(mode):
            result[entry.name] = ("link", os.readlink(entry))
        elif stat.S_ISDIR(mode):
            result[entry.name] = ("directory", stat.S_IMODE(mode), snapshot(entry))
        else:
            permissions = stat.S_IMODE(mode)
            # Read the content of execute-only files, then restore their mode.
            try:
                entry.chmod(permissions | 0o400)
                content = entry.read_bytes()
            finally:
                entry.chmod(permissions)
            result[entry.name] = ("file", permissions, content)
    return result


def setup_fixture(root, kind):
    if kind == "file":
        (root / "foo").write_text("old content")
        (root / "foo").chmod(0o700)
    elif kind == "directory":
        (root / "foo").mkdir()
        (root / "foo" / "keep").write_text("keep me")
    elif kind == "empty-directory":
        (root / "foo").mkdir()
    elif kind in ("file-link", "directory-link", "dangling-link"):
        if kind == "file-link":
            (root / "target").write_text("untouched")
        elif kind == "directory-link":
            (root / "target").mkdir()
            (root / "target" / "keep").write_text("untouched")
        (root / "foo").symlink_to("target")


INVALID_JSON = [
    "", " ", "f", "3 4", "{} {}", "{} trailing", "{", "[", "{,}",
    '{"a": "x",}', '{"a": "x" "b": "y"}', '{,"a": "x"}',
    '{"a": "x",, "b": "y"}', '{"a" "x"}', '{a: "x"}',
    '{"a": ["script", "x",]}', '{"a": "\\q"}', '{"a": "\n"}',
    '{"a": "\\uZZZZ"}', '{"a": "\\uD800"}', '{"a": "\\uDC00"}',
    '{"a": "\\uD800\\u0041"}', '{"a": "unfinished}',
    '{"a": 01}', '{"a": +1}', '{"a": .1}', '{"a": 1.}',
    '{"a": 1e}', '{"a": 1e+}', '{"a": NaN}', '{"a": Infinity}',
    '{"a": 1e309}', '{"a": 1E999999}', '{"a": 0x10}',
    '\ufeff{}', '{}\v', '{"a": truefalse}',
]


def error_category(result):
    message = result.stderr.decode("utf-8", errors="replace")
    categories = [
        "Usage:", "couldn't read stdin", "couldn't convert stdin to JSON",
        "expected provided JSON", "exactly one path component",
        "non-regular path component", "couldn't create a directory",
        "couldn't create a regular file", "couldn't create a script",
        "couldn't create a symlink", "couldn't set the current dir to the newly",
        "to the dir above", "couldn't make the script executable",
        "expected a JSON value", "expected a JSON array to be",
        "expected a JSON array's first element",
    ]
    return next((category for category in categories if category in message), message)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="json2dir-test-")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        for root, dirs, _ in os.walk(self.root):
            Path(root).chmod(0o700)
            for directory in dirs:
                path = Path(root) / directory
                if not path.is_symlink():
                    path.chmod(0o700)
        self.temporary.cleanup()

    def invoke(self, data, **kwargs):
        return run(COMMAND, data, self.root, **kwargs)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")

    def assert_error(self, result, category):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertIn(category, result.stderr.decode("utf-8", errors="replace"))
        self.assertNotIn(b"Backtrace", result.stderr)

    def test_example(self):
        self.assert_success(self.invoke((PROJECT / "example-tree.json").read_bytes()))
        self.assertEqual((self.root / "greeting").read_bytes(), b"Hello, world!")
        self.assertEqual((self.root / "dir" / "subfile").read_bytes(), b"Content.\n")
        self.assertTrue((self.root / "dir" / "subdir").is_dir())
        self.assertEqual(os.readlink(self.root / "symlink"), "target path")
        self.assertEqual(stat.S_IMODE((self.root / "script").stat().st_mode), 0o755)
        output = subprocess.check_output([str(self.root / "script")], cwd=self.root)
        self.assertEqual(output, b"Howdy!\n")

    def test_empty_object(self):
        self.assert_success(self.invoke(" \t\r\n{} \n"))
        self.assertEqual(snapshot(self.root), {})

    def test_arguments(self):
        for args in [("--help",), ("input.json",), ("--",), ("a", "b")]:
            with self.subTest(args=args):
                self.assert_error(self.invoke("{}", args=args), "Usage: json2dir < file.json")

    def test_utf8_independent_of_locale(self):
        text = {"папка": {"привет 😀": "Привет, мир! 😀\n\x00"}}
        env = dict(os.environ, LC_ALL="C", LANG="C")
        result = subprocess.run(
            [COMMAND], input=json.dumps(text, ensure_ascii=False).encode(),
            cwd=self.root, env=env, capture_output=True, timeout=15,
        )
        self.assert_success(result)
        self.assertEqual((self.root / "папка" / "привет 😀").read_bytes(),
                         "Привет, мир! 😀\n\x00".encode())

    def test_string_escapes_and_surrogate_pairs(self):
        self.assert_success(self.invoke(
            r'{"file": "\"\\\/\b\f\n\r\t\u0410\uD83D\uDE00"}'
        ))
        self.assertEqual((self.root / "file").read_bytes(),
                         '"\\/\b\f\n\r\tА😀'.encode())

    def test_invalid_utf8(self):
        for data in [b"\xff", b'{"file":"\xc0\xaf"}', b'{"file":"\xed\xa0\x80"}',
                     b'{}\xff', b'{"file":"\xe2\x82"}']:
            with self.subTest(data=data):
                self.assert_error(self.invoke(data), "couldn't read stdin")
                self.assertEqual(snapshot(self.root), {})

    def test_invalid_json_has_no_side_effects(self):
        for data in INVALID_JSON + ['{"a":"would write", "z":}']:
            with self.subTest(data=data):
                self.assert_error(self.invoke(data), "couldn't convert stdin to JSON")
                self.assertEqual(snapshot(self.root), {})

    def test_root_must_be_object(self):
        for data in ['3', '1.5', '-1e-10', 'true', 'false', 'null', '[]', '"text"']:
            with self.subTest(data=data):
                self.assert_error(self.invoke(data), "expected provided JSON to be an object")

    def test_unsupported_entry_values(self):
        for value in [1, -3.5, True, False, None]:
            with self.subTest(value=value):
                self.assert_error(self.invoke(json.dumps({"foo": value})),
                                  "expected a JSON value")
        for number in ["0e999999", "1e-999999", "1e-309", "1.7976931348623157e308"]:
            self.assert_error(self.invoke('{"foo":' + number + '}'), "expected a JSON value")

    def test_array_validation(self):
        for value in [[], ["link"], ["script", "x", "y"], [1, "x"],
                      ["link", 3], ["script", {}], ["link", None]]:
            with self.subTest(value=value):
                self.assert_error(self.invoke(json.dumps({"foo": value})),
                                  "expected a JSON array to be of the form")
        self.assert_error(self.invoke('{"foo":["unknown","x"]}'),
                          "expected a JSON array's first element")

    def test_rejected_paths(self):
        for name in ["", "/", ".", "..", "../escape", "/absolute", "a/b", "./a"]:
            with self.subTest(name=name):
                self.assertEqual(self.invoke(json.dumps({name: "x"})).returncode, 1)
                self.assertEqual(snapshot(self.root), {})

    def test_single_component_directory_paths(self):
        for name in ["foo/", "foo//", "foo/.", "foo//./"]:
            with self.subTest(name=name):
                self.assert_success(self.invoke(json.dumps({name: {"bar": "x"}})))
                self.assertEqual((self.root / "foo" / "bar").read_bytes(), b"x")

    def test_normal_unusual_names(self):
        names = [".hidden", "..hidden", "has space", "back\\slash", "a:b", "-flag", "line\nbreak"]
        self.assert_success(self.invoke(json.dumps(dict.fromkeys(names, "content"))))
        for name in names:
            self.assertEqual((self.root / name).read_bytes(), b"content")

    def test_existing_files_are_recreated(self):
        setup_fixture(self.root, "file")
        self.assert_success(self.invoke('{"foo":"new"}'))
        self.assertEqual((self.root / "foo").read_bytes(), b"new")
        self.assertEqual(stat.S_IMODE((self.root / "foo").stat().st_mode), 0o644)
        self.assert_success(self.invoke('{"foo":{"bar":"x"}}'))
        self.assertEqual((self.root / "foo" / "bar").read_bytes(), b"x")

    def test_existing_directory_is_merged(self):
        setup_fixture(self.root, "directory")
        self.assert_success(self.invoke('{"foo":{"new":"new"}}'))
        self.assertEqual((self.root / "foo" / "keep").read_bytes(), b"keep me")
        self.assertEqual((self.root / "foo" / "new").read_bytes(), b"new")

    def test_directory_cannot_be_replaced_by_file_or_link(self):
        setup_fixture(self.root, "directory")
        for value, category in [("text", "regular file"), (["script", "text"], "script"),
                                (["link", "target"], "symlink")]:
            with self.subTest(value=value):
                self.assert_error(self.invoke(json.dumps({"foo": value})),
                                  "couldn't create a " + category)
                self.assertEqual((self.root / "foo" / "keep").read_bytes(), b"keep me")

    def test_symlinks_are_unlinked_without_touching_targets(self):
        for kind in ["file-link", "directory-link", "dangling-link"]:
            for value in ["new", {"child": "x"}, ["link", "elsewhere"], ["script", "x"]]:
                with self.subTest(kind=kind, value=value), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    setup_fixture(root, kind)
                    before = snapshot(root).get("target")
                    self.assert_success(run(COMMAND, json.dumps({"foo": value}), root))
                    self.assertEqual(snapshot(root).get("target"), before)

    def test_duplicate_keys_last_value_wins(self):
        self.assert_success(self.invoke('{"foo":3,"foo":"last","dir":{"a":false,"a":"ok"}}'))
        self.assertEqual((self.root / "foo").read_bytes(), b"last")
        self.assertEqual((self.root / "dir" / "a").read_bytes(), b"ok")

    def test_sorted_order_and_partial_changes(self):
        result = self.invoke('{"z":"never","m":null,"a":"created"}')
        self.assert_error(result, "expected a JSON value")
        self.assertEqual(snapshot(self.root), {"a": ("file", 0o644, b"created")})
        self.assertIn(b'"./m"', result.stderr)

    def test_invalid_entry_still_unlinks_existing_file(self):
        setup_fixture(self.root, "file")
        self.assert_error(self.invoke('{"foo":false}'), "expected a JSON value")
        self.assertFalse((self.root / "foo").exists())

    def test_script_permissions_respect_umask_then_add_execute_bits(self):
        for mask, expected in [(0o022, 0o755), (0o077, 0o711), (0o777, 0o111)]:
            with self.subTest(mask=mask):
                self.assert_success(self.invoke('{"foo":["script",""]}', mask=mask))
                self.assertEqual(stat.S_IMODE((self.root / "foo").stat().st_mode), expected)

    def test_nul_in_filename_or_link_target_is_a_clean_error(self):
        (self.root / "bad").write_text("must not be unlinked")
        for value in ["x", {}, ["script", "x"], ["link", "target"]]:
            with self.subTest(value=value):
                self.assert_error(self.invoke(json.dumps({"bad\x00name": value})), "couldn't create")
                self.assertEqual((self.root / "bad").read_text(), "must not be unlinked")
        self.assert_error(self.invoke(json.dumps({"foo": ["link", "bad\x00target"]})),
                          "couldn't create a symlink")

    @unittest.skipIf(os.geteuid() == 0, "permission errors require an unprivileged user")
    def test_permission_errors(self):
        (self.root / "foo").mkdir()
        (self.root / "foo").chmod(0o600)
        self.assert_error(self.invoke('{"foo":{}}'), "couldn't set the current dir")
        (self.root / "foo").chmod(0o500)
        self.assert_error(self.invoke('{"foo":{"bar":"x"}}'), "couldn't create a regular file")

    def test_recursion_limit(self):
        self.assert_success(self.invoke('{"d":' * 126 + '{}' + '}' * 126))
        shutil.rmtree(self.root / "d")
        self.assert_error(self.invoke('{"d":' * 127 + '{}' + '}' * 127),
                          "couldn't convert stdin to JSON")
        self.assertEqual(snapshot(self.root), {})

    def test_library_restores_working_directory_and_locale(self):
        code = r'''
          (use-modules (json2dir core))
          (setlocale LC_CTYPE "C")
          (define start (getcwd))
          (define locale (setlocale LC_CTYPE))
          (define (check-state)
            (unless (and (string=? start (getcwd))
                         (string=? locale (setlocale LC_CTYPE)))
              (error "caller state changed")))
          (parse-and-run "{\"dir\":{\"file\":\"ok\"}}")
          (check-state)
          (unless (catch 'json2dir-error
                    (lambda () (parse-and-run "{\"dir\":{\"bad\":null}}") #f)
                    (lambda args #t))
            (error "expected conversion failure"))
          (check-state)
        '''
        result = subprocess.run(
            [os.environ.get("GUILE", "guile"), "--no-auto-compile",
             "-L", str(PROJECT / "src"), "-c", code],
            cwd=self.root, capture_output=True, timeout=15,
        )
        self.assert_success(result)


@unittest.skipUnless(REFERENCE, "set JSON2DIR_REFERENCE to compare with the Rust binary")
class ParityTests(unittest.TestCase):
    def compare(self, data, fixture=None, args=(), mask=0o022):
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            roots = Path(left), Path(right)
            for root in roots:
                setup_fixture(root, fixture)
            expected = run(REFERENCE, data, roots[0], args, mask)
            actual = run(COMMAND, data, roots[1], args, mask)
            self.assertEqual(actual.returncode, expected.returncode,
                             (data, actual.stderr, expected.stderr))
            self.assertEqual(actual.stdout, expected.stdout)
            self.assertEqual(error_category(actual), error_category(expected),
                             (data, actual.stderr, expected.stderr))
            self.assertEqual(snapshot(roots[1]), snapshot(roots[0]), data)

    def test_fixed_cases(self):
        cases = INVALID_JSON + [
            "{}", "3", "true", "null", "[]", '"x"',
            '{"foo":3}', '{"foo":null}', '{"foo":true}', '{"foo":[]}',
            '{"foo":[1,2]}', '{"foo":["unknown","x"]}',
            '{"foo":3,"foo":"last"}', '{"z":"x","a":false}',
            '{"foo":{"bar":{"":"error"}}}',
            '{"foo":"\\uD83D\\uDE00"}', '{"foo":"\\u0000"}',
            '{"foo":0e999999}', '{"foo":1e-999999}', '{"foo":1e-309}',
            '{"foo":1.7976931348623157e308}', '{"foo":1.7976931348623158e308}',
            '{"d":' * 126 + '{}' + '}' * 126,
            '{"d":' * 127 + '{}' + '}' * 127,
        ]
        for data in cases + [b"\xff", b"{}\xff", b'{"a":"\xc0\xaf"}']:
            with self.subTest(data=data):
                self.compare(data)
        for name in ["", "/", "//", ".", "..", "a/b", "./foo", "foo/", "foo/.",
                     "/foo", "/.", "foo//./", "foo/..", "bad\x00name"]:
            for value in ["text", {}, ["link", "target"]]:
                with self.subTest(name=name, value=value):
                    self.compare(json.dumps({name: value}))
        self.compare("{}", args=("--help",))

    def test_overwrite_matrix(self):
        for fixture in [None, "file", "directory", "empty-directory", "file-link",
                        "directory-link", "dangling-link"]:
            for value in ["new", {}, {"bar": "new"}, ["link", "target"],
                          ["script", "text"], None, ["invalid", "text"]]:
                with self.subTest(fixture=fixture, value=value):
                    self.compare(json.dumps({"foo": value}), fixture)
        for mask in [0o002, 0o022, 0o077, 0o777]:
            self.compare('{"foo":["script","text"]}', mask=mask)

    def test_generated_archives(self):
        rng = random.Random(20261006)
        names = ["plain", ".hidden", "space name", "привет", "emoji😀", "quote\"", "slash\\"]
        texts = ["", "hello", "\x00\n\t", "Привет 😀", "quote\"\\/"]

        def value(depth):
            choices = ["file", "script", "link"] + (["dir"] if depth else [])
            kind = rng.choice(choices)
            if kind == "dir":
                return tree(depth - 1)
            if kind == "file":
                return rng.choice(texts)
            if kind == "link":
                return ["link", rng.choice(["../target", "/", "space target", "привет"])]
            return ["script", rng.choice(texts)]

        def tree(depth):
            return {name: value(depth) for name in rng.sample(names, rng.randrange(5))}

        for index in range(100):
            with self.subTest(index=index):
                self.compare(json.dumps(tree(3), ensure_ascii=index % 2 == 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
