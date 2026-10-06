# json2dir in Scheme

A Guile Scheme port of [alurm/json2dir](https://github.com/alurm/json2dir).
The CLI reads a UTF-8 JSON object from stdin and creates its directory tree in
the current working directory. The implementation is entirely Scheme and uses
Guile 3.0's standard modules, with no external JSON library.

```sh
# From this checkout, with Guile 3.0 on PATH:
cd /path/to/output
/path/to/json2dir-scheme/json2dir < /path/to/example-tree.json

# Or build and run with Nix (Guile is included):
nix build /path/to/json2dir-scheme
nix run /path/to/json2dir-scheme < /path/to/example-tree.json
```

The destination is always the current directory. The command accepts no
arguments, writes errors to stderr, and returns 0 on success or 1 on failure.

## Archive format

```json
{
  "greeting": "Hello, world!",
  "dir": {
    "subfile": "Content.\n",
    "subdir": {}
  },
  "symlink": ["link", "target path"],
  "script": ["script", "#!/bin/sh\necho Howdy!"]
}
```

| JSON value | Filesystem entry |
| --- | --- |
| Object | Directory, populated recursively |
| String | Regular file containing exactly that UTF-8 text |
| `["link", "target"]` | Symbolic link with the given target |
| `["script", "content"]` | Regular file with all three execute bits added |

The root must be an object. Numbers, booleans, null, malformed arrays, and
unknown array tags are rejected. Names must have exactly one normal POSIX path
component: empty names, `.`, `..`, absolute paths, and paths with multiple
components are rejected. Use nested objects for nested directories. As in the
Rust original, trailing separators and interior `.` are normalized when
counting components, so `{"dir/": {}}` is accepted.

## Compatibility

This port preserves the original's Unix behavior:

- JSON is parsed completely before modifying the filesystem. Invalid UTF-8,
  malformed JSON, trailing input, and unpaired Unicode surrogates are rejected.
- Keys are processed in lexical order. Duplicate keys use their last value.
- Existing files and symlinks are unlinked before processing their values.
  Symlink targets are left intact, including targets of directory links.
- Existing directories are reused; unrelated entries remain. A real directory
  cannot be replaced with a file, script, or symlink.
- File and directory permissions follow the OS defaults and umask. Scripts
  additionally receive permission bits `0111`.
- An error can leave changes already made, including removal of an existing
  entry whose replacement value is invalid. There is no transaction or rollback.
- JSON containers are limited to 127 nested levels, matching serde_json's
  default recursion limit. Files contain UTF-8 text, including escaped NUL bytes;
  arbitrary non-UTF-8 binary content is not supported.

The port targets macOS and Linux. Error categories and path context are
preserved; operating-system error details use Guile's diagnostics. As in the
original, concurrent filesystem changes and symlink races are not guarded
against.

## Install

With Guile 3.0 installed:

```sh
make install PREFIX="$HOME/.local"
```

`GUILE` can select an interpreter when running or installing:

```sh
make install PREFIX="$HOME/.local" GUILE=/path/to/guile
GUILE=/path/to/guile ./json2dir < example-tree.json
```

For Nix, `nix build` produces `result/bin/json2dir` and a manual page. The flake
also provides a development shell and checks for macOS and Linux:

```sh
nix develop
make test
nix flake check
```

## Tests

Python 3.9+ is needed only for black-box tests; it is not a runtime dependency.

```sh
make test

# Additionally compare exit/error categories, file contents, permissions,
# directory trees, and symlink targets against the original Rust binary:
JSON2DIR_REFERENCE=/path/to/rust/json2dir make test
```

The parity suite includes malformed input, path edge cases, duplicate keys,
replacement combinations, umasks, and 100 deterministic generated archives.

`src/json2dir/json.scm` contains the strict JSON reader;
`src/json2dir/core.scm` contains filesystem conversion and the CLI;
`src/main.scm` is the entry point. The exported `parse-and-run` procedure
restores the caller's working directory on success and failure.

The original project was inspected at commit `b2072fb` (2026-10-06).
The original's ISC license and attribution are retained in `LICENSE`.
