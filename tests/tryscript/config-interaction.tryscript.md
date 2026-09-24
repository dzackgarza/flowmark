---
sandbox: true
env:
  NO_COLOR: "1"
  LC_ALL: C
path:
  - $TRYSCRIPT_GIT_ROOT/.venv/bin
before: |
  cp -r $TRYSCRIPT_TEST_DIR/fixtures/. fixtures/
---

# Config Interaction Tests

Tests for TOML config file loading, precedence, pyproject.toml, kebab-case keys,
nested sections, the config layered over --auto, CLI overrides, and config errors.

## C1: .flowmark.toml takes precedence over flowmark.toml

The dot-flowmark/ directory has `.flowmark.toml` with width=50 and `flowmark.toml`
with width=60. The `.flowmark.toml` should win.

```console
$ cd fixtures/config-tests/dot-flowmark && flowmark test.md
# Config Test

This is a paragraph that needs to be long enough
to show different wrapping at different widths
clearly.
```

## C2: flowmark.toml with width and semantic

Sentences are split, then wrapped to the config width of 60. A line shorter than 20
characters is joined with the next sentence.

```console
$ cd fixtures/config-tests/flowmark-toml && flowmark test.md
# Config Test

This is a sentence. This is another sentence that follows.

A long paragraph that should wrap at width sixty because the
config file sets that width value for testing.
? 0
```

## C3: pyproject.toml with [tool.flowmark] section

```console
$ cd fixtures/config-tests/pyproject && flowmark test.md
# Pyproject Test

This is a paragraph that needs to be long enough to show wrapping at
width seventy which is the value set in pyproject.toml.
```

## C4: pyproject.toml without [tool.flowmark] uses defaults

```console
$ cd fixtures/config-tests/pyproject-no-section && flowmark test.md
# No Section Test

This is a paragraph that will use default width since pyproject.toml has no flowmark section configured for this test case.
```

## C5: Kebab-case config keys (list-spacing)

```console
$ cd fixtures/config-tests/kebab-case && flowmark test.md
# Kebab Case Config

A list to test:

- Item one

- Item two

- Item three
```

## C6: Nested [formatting] and [file-discovery] sections

```console
$ cd fixtures/config-tests/sections && flowmark test.md
# Sections Config Test

This is the first sentence of the paragraph.
This is the second sentence that follows it closely.

A paragraph long enough to show wrapping at the configured
width of sixty characters for testing.
? 0
```

## C7: CLI flags override config (--width 80 beats config width=50)

```console
$ cd fixtures/config-tests/cli-overrides-config && flowmark --width 80 test.md
# CLI Override Test

This is a paragraph long enough to show different wrapping when CLI width
overrides the config width value.
```

## C8: Config semantic=false overrides the --auto preset

```console
$ cd fixtures/config-tests/auto-lock && flowmark --auto test.md && cat test.md
# Auto Lock Test

First sentence here. Second sentence follows it.

A paragraph to test whether auto mode overrides the config semantic=false setting.
```

## C9: Config from TOML applies to file formatting

```console
$ mkdir -p cfg-width && printf 'width = 40\n' > cfg-width/flowmark.toml && printf '# Narrow\n\nThe quick brown fox jumps over the lazy dog again and again.\n' > cfg-width/narrow.md && cd cfg-width && flowmark narrow.md
# Narrow

The quick brown fox jumps over the lazy
dog again and again.
```

## C10: Config list-spacing and smartquotes survive --auto

The #19 config: `--auto` layers under the config file, so neither setting is dropped.

```console
$ mkdir -p auto-layer && printf '[formatting]\nlist-spacing = "preserve"\nsmartquotes = false\n' > auto-layer/flowmark.toml && printf 'He said "hello". It rests.\n\n- one\n- two\n' > auto-layer/test.md && cd auto-layer && flowmark --auto test.md && cat test.md
He said "hello".
It rests.

- one
- two
```

## C11: An explicit flag overrides the config file

```console
$ mkdir -p cli-beats-cfg && printf 'smartquotes = true\n' > cli-beats-cfg/flowmark.toml && printf 'He said "hello".\n' > cli-beats-cfg/test.md && cd cli-beats-cfg && flowmark --no-smartquotes test.md
He said "hello".
```

## C12: An unknown config key fails without formatting

```console
$ mkdir -p bad-key && printf '[formatting]\nsmart-quotes = true\n' > bad-key/flowmark.toml && printf '# T\n' > bad-key/test.md && cd bad-key && flowmark test.md
Error: [CWD]/bad-key/flowmark.toml: unknown config key 'smart-quotes'
? 1
```

## C13: A config value of the wrong type fails without formatting

```console
$ mkdir -p bad-type && printf 'width = "wide"\n' > bad-type/flowmark.toml && printf '# T\n' > bad-type/test.md && cd bad-type && flowmark test.md
Error: [CWD]/bad-type/flowmark.toml: config key 'width' must be int, not str
? 1
```

## C14: An unknown list-spacing value fails without formatting

```console
$ mkdir -p bad-choice && printf 'list-spacing = "compact"\n' > bad-choice/flowmark.toml && printf '# T\n' > bad-choice/test.md && cd bad-choice && flowmark test.md
Error: [CWD]/bad-choice/flowmark.toml: config key 'list-spacing' must be one of preserve, loose, tight, not 'compact'
? 1
```

## C15: An unparsable config file fails without formatting

```console
$ mkdir -p bad-toml && printf 'this is not toml [[[\n' > bad-toml/flowmark.toml && printf '# T\n' > bad-toml/test.md && cd bad-toml && flowmark test.md
Error: [CWD]/bad-toml/flowmark.toml: Expected '=' after a key in a key/value pair (at line 1, column 6)
? 1
```
