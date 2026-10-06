PREFIX ?= /usr/local
DESTDIR ?=
GUILE ?= guile
PYTHON ?= python3

.PHONY: all test install
all:

test:
	GUILE="$(GUILE)" $(PYTHON) tests/test_cli.py

install:
	install -d "$(DESTDIR)$(PREFIX)/bin" "$(DESTDIR)$(PREFIX)/share/json2dir/src/json2dir" "$(DESTDIR)$(PREFIX)/share/man/man1" "$(DESTDIR)$(PREFIX)/share/licenses/json2dir"
	install -m 644 src/json2dir/*.scm "$(DESTDIR)$(PREFIX)/share/json2dir/src/json2dir/"
	install -m 644 src/main.scm "$(DESTDIR)$(PREFIX)/share/json2dir/src/"
	install -m 644 json2dir.1 "$(DESTDIR)$(PREFIX)/share/man/man1/"
	install -m 644 LICENSE "$(DESTDIR)$(PREFIX)/share/licenses/json2dir/"
	printf '%s\n' '#!/bin/sh' 'exec "$${GUILE:-$(GUILE)}" --no-auto-compile -L "$(PREFIX)/share/json2dir/src" -s "$(PREFIX)/share/json2dir/src/main.scm" "$$@"' > "$(DESTDIR)$(PREFIX)/bin/json2dir"
	chmod 755 "$(DESTDIR)$(PREFIX)/bin/json2dir"
