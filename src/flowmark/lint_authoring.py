"""Mathematical-authoring lint rules for Pandoc Markdown.

These rules cover TeX inside math and raw TeX (commands, macros, resources),
notation, cross-references, citations and TikZ compiler findings. Data that
only a host environment knows (macro source paths, workspace reference
resolutions, bibliography keys, compiler output) arrives as plain JSON through
``RuleContext.data``; the rule decisions live here.
"""

from __future__ import annotations

import glob
import json
import os
import re
from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import flowmark.lint_rules as core
from flowmark.lint_engine import (
    LintRule,
    RuleCheck,
    RuleContext,
    RuleFinding,
    RuleLevel,
    RuleRegistry,
)
from flowmark.pandoc_lint import PandocJson, pandoc_plain, walk_pandoc

_CONTROL_WORD = re.compile(r"(?<!\\)\\([A-Za-z@]+)")
_DECLARATION = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand|"
    + r"DeclareMathOperator|DeclarePairedDelimiter(?:X|XPP)?|NewDocumentCommand|"
    + r"RenewDocumentCommand|ProvideDocumentCommand|DeclareDocumentCommand|"
    + r"NewExpandableDocumentCommand|RenewExpandableDocumentCommand|newrobustcmd|"
    + r"renewrobustcmd|providerobustcmd)\*?\s*(?:\{\s*)?\\([A-Za-z@]+)"
    + r"|\\(?:def|gdef|edef|xdef)\s*\\([A-Za-z@]+)"
    + r"|\\let\s*\\([A-Za-z@]+)"
)
_NOTATION_VARIANTS = (
    ("\\epsilon", "\\varepsilon"),
    ("\\phi", "\\varphi"),
    ("\\theta", "\\vartheta"),
    ("\\rho", "\\varrho"),
    ("\\sigma", "\\varsigma"),
    ("\\kappa", "\\varkappa"),
)
_AUTHORIAL_RESIDUE = (
    (re.compile(r"\b(?:TODO|FIXME|XXX)\b"), "unfinished-note", "Unfinished note"),
    (
        re.compile(r"\[\s*citation needed\s*\]", re.IGNORECASE),
        "citation-placeholder",
        "Citation placeholder",
    ),
    (re.compile(r"\bCITE(?:ME)?\b"), "citation-placeholder", "Citation placeholder"),
    (re.compile(r"\?\?\?"), "unresolved-placeholder", "Unresolved placeholder"),
    (re.compile(r"\\todo\b"), "todo-command", "TODO command"),
)
_TEX_INPUT = re.compile(r"(?<!\\)\\(?:input|include)\s*\{(?P<path>[^{}\n]+)\}")
_TEX_GRAPHICS = re.compile(
    r"(?<!\\)\\includegraphics(?:\s*\[[^\]\n]*\])?\s*\{(?P<path>[^{}\n]+)\}"
)
_TEX_GRAPHICSPATH = re.compile(
    r"(?<!\\)\\graphicspath\s*\{(?P<paths>(?:\s*\{[^{}\n]*\}\s*)+)\}"
)
_TEX_GRAPHICSPATH_ENTRY = re.compile(r"\{(?P<path>[^{}\n]*)\}")
_GRAPHICS_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps")
_MACRO_SOURCE_EXTENSIONS = frozenset({".tex", ".sty", ".cls", ".json"})
_SIMPLE_COMMAND_DEFINITION = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)\*?"
    + r"\s*(?:\{\s*)?\\(?P<name>[A-Za-z@]+)\s*\}?\s*"
)
_OPERATOR_DEFINITION = re.compile(
    r"\\DeclareMathOperator(?P<star>\*)?\s*\{\s*\\(?P<name>[A-Za-z@]+)\s*\}\s*"
)
_DEF_DEFINITION = re.compile(r"\\(?:def|gdef|edef|xdef)\s*\\(?P<name>[A-Za-z@]+)\s*")
_PAIRED_DELIMITER_DEFINITION = re.compile(
    r"\\DeclarePairedDelimiter(?:X|XPP)?\*?\s*(?:\{\s*)?"
    + r"\\(?P<name>[A-Za-z@]+)\s*\}?\s*"
)
_IGNORED_MATCH_CONTROL_WORDS = frozenset({"left", "right", "quad", "qquad"})
_IGNORED_MATCH_CONTROL_SYMBOLS = frozenset({",", "!", ";", ":", " "})
_PACKAGE_DECLARATION = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\]\s*)?\{(?P<names>[^{}]+)\}"
)
_DOCUMENT_CLASS_DECLARATION = re.compile(
    r"\\documentclass\s*(?:\[[^\]]*\]\s*)?\{(?P<name>[^{}]+)\}"
)


@dataclass(frozen=True)
class _TexstudioPackage:
    commands: tuple[str, ...]
    includes: tuple[str, ...]


@dataclass(frozen=True)
class _TexstudioIndex:
    packages: Mapping[str, _TexstudioPackage]
    core: tuple[str, ...]
    core_commands: frozenset[str]


@dataclass(frozen=True)
class _TexstudioVocabulary:
    commands: frozenset[str]
    packages: frozenset[str]


def _load_texstudio_index() -> _TexstudioIndex:
    path = Path(__file__).with_name("data") / "texstudio-command-index.json"
    raw = cast(object, json.loads(path.read_text()))
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid TeXstudio command index: {path}")
    root = cast(dict[str, object], raw)
    packages_value = root.get("packages")
    core_value = root.get("core")
    if not isinstance(packages_value, dict) or not isinstance(core_value, list):
        raise ValueError(f"Invalid TeXstudio command index: {path}")
    packages_raw = cast(dict[str, object], packages_value)
    core_raw = cast(list[object], core_value)

    def strings(value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            items = cast(list[object], value)
            return tuple(item for item in items if isinstance(item, str))
        return ()

    packages: dict[str, _TexstudioPackage] = {}
    for raw_name, raw_entry in packages_raw.items():
        if not isinstance(raw_entry, dict):
            continue
        entry = cast(dict[str, object], raw_entry)
        commands = tuple(sorted(strings(entry.get("commands"))))
        includes = strings(entry.get("includes"))
        packages[raw_name] = _TexstudioPackage(commands, includes)

    core = tuple(item for item in core_raw if isinstance(item, str))
    core_commands, _active = _texstudio_package_closure(packages, core)
    return _TexstudioIndex(packages, core, frozenset(core_commands))


def _texstudio_package_closure(
    packages: Mapping[str, _TexstudioPackage],
    roots: Iterable[str],
) -> tuple[set[str], set[str]]:
    commands: set[str] = set()
    active: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in active:
            continue
        package = packages.get(name)
        if package is None:
            continue
        active.add(name)
        commands.update(package.commands)
        pending.extend(package.includes)
    return commands, active


_TEXSTUDIO_INDEX = _load_texstudio_index()
_TEXSTUDIO_PROVIDER_CACHE: dict[str, tuple[str, ...]] = {}


@dataclass(frozen=True)
class _MacroInventory:
    commands: frozenset[str]
    definitions: tuple["_MacroDefinition", ...]


@dataclass(frozen=True)
class _MacroDefinition:
    name: str
    replacement: str
    argument_count: int


@dataclass(frozen=True)
class _NormalizedTex:
    text: str
    positions: tuple[int, ...]


def _section(context: RuleContext, name: str) -> Mapping[str, object]:
    value = context.data.get(name)
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _tex(context: RuleContext) -> Mapping[str, object]:
    return _section(context, "tex")


def _references(context: RuleContext) -> Mapping[str, object]:
    return _section(context, "references")


def _compiler(context: RuleContext) -> Mapping[str, object]:
    return _section(context, "compiler")


def _strings(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [str(item) for item in value]
    return []


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _package_names_from_tex(source: str) -> tuple[set[str], set[str]]:
    visible = core.mask_tex_comments(source)
    packages: set[str] = set()
    classes: set[str] = set()
    for match in _PACKAGE_DECLARATION.finditer(visible):
        packages.update(
            name.strip() for name in match.group("names").split(",") if name.strip()
        )
    for match in _DOCUMENT_CLASS_DECLARATION.finditer(visible):
        name = match.group("name").strip()
        if name:
            classes.add(name)
    return packages, classes


def _raw_tex_fragments(context: RuleContext) -> Iterable[str]:
    for node in walk_pandoc(context.pandoc_document):
        if node.get("t") not in {"RawInline", "RawBlock"}:
            continue
        content = node.get("c")
        if not isinstance(content, list) or len(content) != 2:
            continue
        format_name, source = content
        if format_name in {"tex", "latex"} and isinstance(source, str):
            yield source


def _texstudio_vocabulary(
    context: RuleContext,
    data: Mapping[str, object],
) -> tuple[frozenset[str], frozenset[str]]:
    cached = context.cache.get("authoring/texstudio-vocabulary")
    if isinstance(cached, _TexstudioVocabulary):
        return cached.commands, cached.packages

    package_roots = set(_strings(data.get("packages")))
    class_roots = set(_strings(data.get("classes")))
    for fragment in _raw_tex_fragments(context):
        packages, classes = _package_names_from_tex(fragment)
        package_roots.update(packages)
        class_roots.update(classes)

    for path in _macro_source_files(context, data):
        if path.suffix.casefold() not in {".tex", ".sty", ".cls"}:
            continue
        try:
            packages, classes = _package_names_from_tex(path.read_text())
        except OSError:
            continue
        package_roots.update(packages)
        class_roots.update(classes)

    roots = set(package_roots)
    for name in class_roots:
        class_name = f"class-{name}"
        roots.add(class_name if class_name in _TEXSTUDIO_INDEX.packages else name)

    package_commands, active_packages = _texstudio_package_closure(
        _TEXSTUDIO_INDEX.packages,
        roots,
    )
    result = _TexstudioVocabulary(
        frozenset(_TEXSTUDIO_INDEX.core_commands | package_commands),
        frozenset(set(_TEXSTUDIO_INDEX.core) | active_packages),
    )
    context.cache["authoring/texstudio-vocabulary"] = result
    return result.commands, result.packages


def _texstudio_command_providers(command: str) -> tuple[str, ...]:
    cached = _TEXSTUDIO_PROVIDER_CACHE.get(command)
    if cached is not None:
        return cached
    providers: list[str] = []
    for name, package in _TEXSTUDIO_INDEX.packages.items():
        index = bisect_left(package.commands, command)
        if index < len(package.commands) and package.commands[index] == command:
            providers.append(name)
    result = tuple(sorted(providers))
    _TEXSTUDIO_PROVIDER_CACHE[command] = result
    return result


def _normalize_command_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name:
        return None
    if not name.startswith("\\"):
        name = "\\" + name
    return name if re.fullmatch(r"\\[A-Za-z@]+", name) is not None else None


def _balanced_group(source: str, start: int) -> tuple[str, int] | None:
    if start >= len(source) or source[start] != "{":
        return None
    depth = 0
    index = start
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index], index + 1
        index += 1
    return None


def _skip_space(source: str, start: int) -> int:
    index = start
    while index < len(source) and source[index].isspace():
        index += 1
    return index


def _bracket_group(source: str, start: int) -> tuple[str, int] | None:
    if start >= len(source) or source[start] != "[":
        return None
    depth = 0
    index = start
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index], index + 1
        index += 1
    return None


def _inferred_argument_count(replacement: str) -> int:
    indices = [int(match.group(1)) for match in re.finditer(r"#([1-9])", replacement)]
    return max(indices, default=0)


def _tex_macro_definitions(source: str) -> tuple[set[str], list[_MacroDefinition]]:
    visible = core.mask_tex_comments(source)
    commands: set[str] = set()
    definitions: list[_MacroDefinition] = []
    for match in _DECLARATION.finditer(visible):
        name = match.group(1) or match.group(2) or match.group(3)
        if name:
            commands.add("\\" + name)

    for match in _SIMPLE_COMMAND_DEFINITION.finditer(visible):
        name = "\\" + match.group("name")
        cursor = _skip_space(visible, match.end())
        argument_count = 0
        option = _bracket_group(visible, cursor)
        if option is not None and option[0].strip().isdigit():
            argument_count = int(option[0].strip())
            cursor = _skip_space(visible, option[1])
            default = _bracket_group(visible, cursor)
            if default is not None:
                cursor = _skip_space(visible, default[1])
        if cursor >= len(visible) or visible[cursor] != "{":
            continue
        group = _balanced_group(visible, cursor)
        if group is not None:
            _masked_body, end = group
            replacement = source[cursor + 1 : end - 1].strip()
            definitions.append(
                _MacroDefinition(
                    name,
                    replacement,
                    max(argument_count, _inferred_argument_count(replacement)),
                )
            )

    for match in _OPERATOR_DEFINITION.finditer(visible):
        name = "\\" + match.group("name")
        cursor = match.end()
        if cursor >= len(visible) or visible[cursor] != "{":
            continue
        group = _balanced_group(visible, cursor)
        if group is None:
            continue
        _masked_body, end = group
        body = source[cursor + 1 : end - 1].strip()
        operator = "\\operatorname*" if match.group("star") else "\\operatorname"
        definitions.append(_MacroDefinition(name, f"{operator}{{{body}}}", 0))

    for match in _DEF_DEFINITION.finditer(visible):
        name = "\\" + match.group("name")
        cursor = match.end()
        body_start = visible.find("{", cursor)
        if body_start < 0:
            continue
        parameter_text = visible[cursor:body_start]
        if "##" in parameter_text:
            commands.discard(name)
            continue
        group = _balanced_group(visible, body_start)
        if group is not None:
            _masked_body, end = group
            replacement = source[body_start + 1 : end - 1].strip()
            parameter_count = max(
                (
                    int(parameter.group(1))
                    for parameter in re.finditer(r"#([1-9])", parameter_text)
                ),
                default=0,
            )
            definitions.append(
                _MacroDefinition(
                    name,
                    replacement,
                    max(parameter_count, _inferred_argument_count(replacement)),
                )
            )

    for match in _PAIRED_DELIMITER_DEFINITION.finditer(visible):
        name = "\\" + match.group("name")
        cursor = _skip_space(visible, match.end())
        left = _balanced_group(visible, cursor)
        if left is None:
            continue
        cursor = _skip_space(visible, left[1])
        right = _balanced_group(visible, cursor)
        if right is None:
            continue
        left_body = left[0]
        right_body = right[0]
        definitions.append(_MacroDefinition(name, f"{left_body}#1{right_body}", 1))

    return commands, definitions


def _json_macro_mapping(value: object) -> Mapping[str, object]:
    root = _mapping(value)
    tex = _mapping(root.get("tex"))
    tex_macros = _mapping(tex.get("macros"))
    if tex_macros:
        return tex_macros
    macros = _mapping(root.get("macros"))
    return macros if macros else root


def _macro_definition(name: str, value: object) -> _MacroDefinition | None:
    replacement: str | None = None
    argument_count = 0
    if isinstance(value, str):
        replacement = value.strip()
    if isinstance(value, Sequence) and not isinstance(value, str) and value:
        first = value[0]
        replacement = first.strip() if isinstance(first, str) else None
        if len(value) > 1 and isinstance(value[1], int):
            argument_count = value[1]
    mapping = _mapping(value)
    mapped_replacement = mapping.get("replacement")
    if isinstance(mapped_replacement, str):
        replacement = mapped_replacement.strip()
    mapped_count = mapping.get("argumentCount")
    if isinstance(mapped_count, int):
        argument_count = mapped_count
    if not replacement:
        return None
    return _MacroDefinition(
        name,
        replacement,
        max(argument_count, _inferred_argument_count(replacement)),
    )


def _macro_source_base(context: RuleContext, data: Mapping[str, object]) -> Path:
    default = (
        context.source_path.parent if context.source_path is not None else Path.cwd()
    )
    raw = data.get("macro_base")
    if not isinstance(raw, str) or not raw.strip():
        return default
    expanded = Path(os.path.expandvars(raw)).expanduser()
    return (
        expanded.resolve() if expanded.is_absolute() else (default / expanded).resolve()
    )


def _macro_source_files(context: RuleContext, data: Mapping[str, object]) -> list[Path]:
    base = _macro_source_base(context, data)
    resolved: dict[str, Path] = {}
    for spec in _strings(data.get("macro_sources")):
        expanded = os.path.expandvars(os.path.expanduser(spec))
        candidate = Path(expanded)
        if not candidate.is_absolute():
            candidate = base / candidate

        matches: list[Path]
        if any(char in str(candidate) for char in "*?["):
            matches = [Path(item) for item in glob.glob(str(candidate), recursive=True)]
        elif candidate.exists():
            matches = [candidate]
        else:
            raise ValueError(f"Macro source does not exist: {spec}")

        for match in matches:
            if match.is_dir():
                for file_path in sorted(match.rglob("*")):
                    if (
                        file_path.is_file()
                        and file_path.suffix.casefold() in _MACRO_SOURCE_EXTENSIONS
                    ):
                        resolved[str(file_path.resolve())] = file_path.resolve()
            elif (
                match.is_file() and match.suffix.casefold() in _MACRO_SOURCE_EXTENSIONS
            ):
                resolved[str(match.resolve())] = match.resolve()

    return [resolved[key] for key in sorted(resolved)]


def _macro_inventory(
    context: RuleContext,
) -> tuple[frozenset[str], tuple[_MacroDefinition, ...]]:
    cached = context.cache.get("authoring/macro-inventory")
    if isinstance(cached, _MacroInventory):
        return cached.commands, cached.definitions

    data = _tex(context)
    texstudio_commands, _active_packages = _texstudio_vocabulary(context, data)
    commands = set(texstudio_commands)
    definitions: dict[str, _MacroDefinition] = {}

    for raw in _strings(data.get("known_commands")):
        name = _normalize_command_name(raw)
        if name is not None:
            commands.add(name)

    direct_macros = _mapping(data.get("macros"))
    for raw_name, definition in direct_macros.items():
        name = _normalize_command_name(raw_name)
        if name is None:
            continue
        commands.add(name)
        macro = _macro_definition(name, definition)
        if macro is not None:
            definitions[name] = macro

    for path in _macro_source_files(context, data):
        if path.suffix.casefold() == ".json":
            try:
                value = cast(object, json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"Cannot read macro source {path}: {error}") from error
            for raw_name, definition in _json_macro_mapping(value).items():
                name = _normalize_command_name(raw_name)
                if name is None:
                    continue
                commands.add(name)
                macro = _macro_definition(name, definition)
                if macro is not None:
                    definitions[name] = macro
            continue

        try:
            source = path.read_text()
        except OSError as error:
            raise ValueError(f"Cannot read macro source {path}: {error}") from error
        file_commands, file_definitions = _tex_macro_definitions(source)
        commands.update(file_commands)
        for definition in file_definitions:
            definitions[definition.name] = definition

    commands.update(_local_macro_names(context))
    result = _MacroInventory(
        frozenset(commands),
        tuple(definitions[name] for name in sorted(definitions)),
    )
    context.cache["authoring/macro-inventory"] = result
    return result.commands, result.definitions


def _normalize_tex_for_macro_match(source: str) -> _NormalizedTex:
    chars: list[str] = []
    positions: list[int] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace() or char in {"~", "{", "}"}:
            index += 1
            continue
        if char != "\\":
            chars.append(char)
            positions.append(index)
            index += 1
            continue

        if index + 1 >= len(source):
            chars.append(char)
            positions.append(index)
            index += 1
            continue

        next_char = source[index + 1]
        if next_char.isalpha() or next_char == "@":
            end = index + 2
            while end < len(source) and (source[end].isalpha() or source[end] == "@"):
                end += 1
            word = source[index + 1 : end]
            if word in _IGNORED_MATCH_CONTROL_WORDS:
                index = end
                continue
            for offset in range(index, end):
                chars.append(source[offset])
                positions.append(offset)
            index = end
            continue

        if next_char in _IGNORED_MATCH_CONTROL_SYMBOLS:
            index += 2
            continue
        chars.extend(("\\", next_char))
        positions.extend((index, index + 1))
        index += 2

    return _NormalizedTex("".join(chars), tuple(positions))


def _macro_pattern(definition: _MacroDefinition) -> re.Pattern[str] | None:
    normalized = _normalize_tex_for_macro_match(definition.replacement).text
    placeholders = list(re.finditer(r"#([1-9])", normalized))
    fixed = re.sub(r"#([1-9])", "", normalized)
    if len(fixed) < 4:
        return None

    parts: list[str] = []
    cursor = 0
    seen: set[int] = set()
    for placeholder in placeholders:
        parts.append(re.escape(normalized[cursor : placeholder.start()]))
        number = int(placeholder.group(1))
        if number in seen:
            parts.append(f"(?P=a{number})")
        else:
            parts.append(f"(?P<a{number}>.+?)")
            seen.add(number)
        cursor = placeholder.end()
    parts.append(re.escape(normalized[cursor:]))
    pattern = "".join(parts)
    if not pattern:
        return None
    return re.compile(pattern)


def _macro_invocation(definition: _MacroDefinition) -> str:
    return definition.name + "{…}" * definition.argument_count


def _source_analysis(context: RuleContext) -> dict[str, object]:
    cached = context.cache.get("authoring/source-analysis")
    if isinstance(cached, dict):
        return cast(dict[str, object], cached)

    lines = core.source_lines(context.text)
    frontmatter = core.source_frontmatter(lines)
    frontmatter_lines: set[int] = set()
    if frontmatter is not None:
        last = (
            frontmatter.closing.number
            if frontmatter.closing is not None
            else lines[-1].number
        )
        frontmatter_lines.update(range(frontmatter.opening.number, last + 1))
    fences = core.source_fences(lines, frontmatter_lines)
    protected = core.source_protected_map(context.text, lines, frontmatter, fences)
    literal = core.source_literal_protected_map(context.text, frontmatter, fences)
    math = core.pandoc_math_regions(context.text, context.pandoc_document)
    result: dict[str, object] = {
        "lines": lines,
        "frontmatter": frontmatter,
        "fences": fences,
        "protected": protected,
        "literal": literal,
        "math": math,
    }
    context.cache["authoring/source-analysis"] = result
    return result


def _local_macro_names(context: RuleContext) -> set[str]:
    cached = context.cache.get("authoring/local-macros")
    if isinstance(cached, set):
        return cast(set[str], cached)
    literal = cast(bytearray, _source_analysis(context)["literal"])
    visible = core.mask_tex_comments(context.text)
    names: set[str] = set()
    for match in _DECLARATION.finditer(visible):
        if core.protected_overlap(literal, match.start(), match.end()):
            continue
        name = match.group(1) or match.group(2) or match.group(3)
        if name:
            names.add("\\" + name)
    context.cache["authoring/local-macros"] = names
    return names


def _unknown_tex_commands(
    context: RuleContext,
    _options: Mapping[str, object],
) -> Iterable[RuleFinding]:
    known, _expansions = _macro_inventory(context)

    findings: list[RuleFinding] = []
    seen: set[int] = set()
    for start, end in cast(list[tuple[int, int]], _source_analysis(context)["math"]):
        source = context.text[start:end]
        for match in _CONTROL_WORD.finditer(source):
            absolute = start + match.start()
            command = "\\" + match.group(1)
            if absolute in seen or command in known:
                continue
            seen.add(absolute)
            providers = _texstudio_command_providers(command)
            if providers:
                visible = ", ".join(providers[:8])
                extra = len(providers) - 8
                message = (
                    f"{command} is known from TeX package data, but none of its "
                    + f"providing packages are active here. Providers: {visible}"
                    + (f" (+{extra} more)." if extra > 0 else ".")
                )
                data = {
                    "command": command,
                    "kind": "inactive-package",
                    "providers": providers,
                }
            else:
                message = (
                    f"No definition for {command} was found in this document, the "
                    + "active TeX/LaTeX packages, or the available macro sources."
                )
                data = {"command": command, "kind": "unknown"}
            findings.append(
                RuleFinding(
                    "tex/unknown-command",
                    "warning",
                    message,
                    absolute,
                    absolute + len(match.group(0)),
                    data=data,
                )
            )
    return findings


def _command_offsets(source: str, offset: int, command: str) -> list[int]:
    pattern = re.compile(re.escape(command) + r"(?![A-Za-z@])")
    return [offset + match.start() for match in pattern.finditer(source)]


def _notation_consistency(
    context: RuleContext,
    _options: Mapping[str, object],
) -> Iterable[RuleFinding]:
    findings: list[RuleFinding] = []
    regions = cast(list[tuple[int, int]], _source_analysis(context)["math"])
    for first, second in _NOTATION_VARIANTS:
        first_offsets: list[int] = []
        second_offsets: list[int] = []
        for start, end in regions:
            source = context.text[start:end]
            first_offsets.extend(_command_offsets(source, start, first))
            second_offsets.extend(_command_offsets(source, start, second))
        if (
            not first_offsets
            or not second_offsets
            or len(first_offsets) == len(second_offsets)
        ):
            continue
        if len(first_offsets) > len(second_offsets):
            majority, majority_count, minority, minority_offsets = (
                first,
                len(first_offsets),
                second,
                second_offsets,
            )
        else:
            majority, majority_count, minority, minority_offsets = (
                second,
                len(second_offsets),
                first,
                first_offsets,
            )
        if majority_count < 2:
            continue
        for start in minority_offsets:
            findings.append(
                RuleFinding(
                    "math/notation-consistency",
                    "info",
                    f"Both {majority} and {minority} appear in this document; "
                    + f"{majority} appears {majority_count} times, while this occurrence "
                    + f"uses {minority}. If they are intended to denote the same symbol, "
                    + "choose one form consistently.",
                    start,
                    start + len(minority),
                )
            )
    return findings


def _user_macro_candidates(
    context: RuleContext,
    _options: Mapping[str, object],
) -> Iterable[RuleFinding]:
    _known, definitions = _macro_inventory(context)
    patterns = [
        (definition, pattern)
        for definition in definitions
        if (pattern := _macro_pattern(definition)) is not None
    ]
    span_candidates: dict[tuple[int, int], dict[str, _MacroDefinition]] = {}
    for start, end in cast(list[tuple[int, int]], _source_analysis(context)["math"]):
        source = context.text[start:end]
        normalized = _normalize_tex_for_macro_match(source)
        if not normalized.text:
            continue
        for definition, pattern in patterns:
            for match in pattern.finditer(normalized.text):
                if match.start() == match.end():
                    continue
                authored_from = start + normalized.positions[match.start()]
                authored_to = start + normalized.positions[match.end() - 1] + 1
                span_candidates.setdefault((authored_from, authored_to), {})[
                    definition.name
                ] = definition

    findings: list[RuleFinding] = []
    spans = sorted(span_candidates)
    for authored_from, authored_to in spans:
        candidates_by_name = span_candidates[(authored_from, authored_to)]
        if all(
            candidate.argument_count == 0 for candidate in candidates_by_name.values()
        ) and any(
            outer_from <= authored_from
            and authored_to <= outer_to
            and (outer_from, outer_to) != (authored_from, authored_to)
            for outer_from, outer_to in spans
        ):
            continue
        candidates = [
            _macro_invocation(candidates_by_name[name])
            for name in sorted(candidates_by_name)
        ]
        if len(candidates) == 1:
            message = (
                "This manual construction may be replaceable by a known user macro: "
                + candidates[0]
                + "."
            )
        else:
            message = (
                "This manual construction may be replaceable by known user macros: "
                + ", ".join(candidates)
                + "."
            )
        findings.append(
            RuleFinding(
                "math/user-macro-candidates",
                "info",
                message,
                authored_from,
                authored_to,
                data={"candidates": tuple(candidates)},
            )
        )
    return findings


def _authorial_residue(
    context: RuleContext,
    _options: Mapping[str, object],
) -> Iterable[RuleFinding]:
    protected = cast(bytearray, _source_analysis(context)["protected"])
    findings: list[RuleFinding] = []
    for pattern, kind, description in _AUTHORIAL_RESIDUE:
        for match in pattern.finditer(context.text):
            if core.protected_overlap(protected, match.start(), match.end()):
                continue
            findings.append(
                RuleFinding(
                    "document/authorial-residue",
                    "info",
                    f"Possible authoring residue: {match.group(0)!r} "
                    + f"({description.casefold()}).",
                    match.start(),
                    match.end(),
                    data={"kind": kind, "marker": match.group(0)},
                )
            )
    return findings


def _raw_tex_regions(context: RuleContext) -> list[tuple[int, int]]:
    cached = context.cache.get("authoring/raw-tex-regions")
    if isinstance(cached, list):
        return cast(list[tuple[int, int]], cached)
    regions: list[tuple[int, int]] = []
    cursor = 0
    for node in walk_pandoc(context.pandoc_document):
        if node.get("t") not in {"RawInline", "RawBlock"}:
            continue
        content = node.get("c")
        if not isinstance(content, list) or len(content) != 2:
            continue
        fmt, raw = content
        format_name = fmt.get("c") if isinstance(fmt, dict) else fmt
        if format_name not in {"tex", "latex"} or not isinstance(raw, str) or not raw:
            continue
        found = context.text.find(raw, cursor)
        if found < 0:
            found = context.text.find(raw)
        if found < 0:
            continue
        regions.append((found, found + len(raw)))
        cursor = found + len(raw)
    context.cache["authoring/raw-tex-regions"] = regions
    return regions


def _static_path(value: str) -> bool:
    return (
        bool(value.strip())
        and not re.search(r"[\\$#*?]", value)
        and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value)
    )


def _candidate_names(path: str, kind: str) -> list[str]:
    if Path(path).suffix:
        return [path]
    if kind == "input":
        return [path, path + ".tex"]
    return [path, *(path + suffix for suffix in _GRAPHICS_EXTENSIONS)]


def _recursive_files(context: RuleContext, root: Path) -> list[Path]:
    key = f"authoring/files/{root.resolve()}"
    cached = context.cache.get(key)
    if isinstance(cached, list):
        return cast(list[Path], cached)
    files = (
        [path for path in root.rglob("*") if path.is_file()] if root.is_dir() else []
    )
    context.cache[key] = files
    return files


def _resolve_in_root(
    context: RuleContext,
    root: Path,
    names: Sequence[str],
    *,
    recursive: bool,
) -> Path | None:
    for name in names:
        candidate = (root / name).resolve()
        if candidate.is_file():
            return candidate
    if not recursive:
        return None
    files = _recursive_files(context, root)
    for name in names:
        normalized = name.replace("\\", "/").removeprefix("./")
        basename = Path(normalized).name
        for candidate in files:
            unix = candidate.as_posix()
            if unix.endswith("/" + normalized) or (
                "/" not in normalized and candidate.name == basename
            ):
                return candidate
    return None


def _resource_exists(
    context: RuleContext,
    authored: str,
    kind: str,
    graphic_roots: Sequence[str],
) -> bool | None:
    if not _static_path(authored):
        return None
    data = _tex(context)
    source_dir = context.source_path.parent if context.source_path is not None else None
    project_roots = [
        Path(root).expanduser() for root in _strings(data.get("project_roots"))
    ]
    home = Path(str(data.get("home_directory") or Path.home())).expanduser()
    names = _candidate_names(authored.strip(), kind)

    authored_path = Path(authored.strip()).expanduser()
    if authored_path.is_absolute():
        return any((authored_path.parent / Path(name).name).is_file() for name in names)

    ordinary: list[tuple[Path, bool]] = []
    if source_dir is not None:
        ordinary.append((source_dir, False))
    ordinary.extend((root, False) for root in project_roots)
    ordinary.extend(
        (
            root,
            recursive,
        )
        for root, recursive in (
            (home / ".pandoc" / "styles", True),
            (home / ".pandoc" / "styles" / "macros", True),
            (home / ".pandoc" / "macros", True),
            (home / ".pandoc" / "config", True),
            (home / ".pandoc", False),
            (home / ".pandoc" / "figures", False),
        )
    )
    texinputs = str(data.get("texinputs") or os.environ.get("TEXINPUTS", ""))
    for raw in texinputs.split(os.pathsep):
        if not raw:
            continue
        recursive = raw.endswith("//")
        root = raw[:-2] if recursive else raw
        if root:
            ordinary.append((Path(root).expanduser(), recursive))

    roots = list(ordinary)
    if kind == "graphics":
        bases = [root for root in [source_dir, *project_roots] if root is not None]
        graphics: list[tuple[Path, bool]] = []
        for graphic in graphic_roots:
            if not _static_path(graphic):
                continue
            for base in bases:
                graphics.append(((base / graphic).resolve(), False))
        roots = graphics + roots
    return any(
        _resolve_in_root(context, root, names, recursive=recursive) is not None
        for root, recursive in roots
    )


def _tex_missing_resource(
    context: RuleContext,
    _options: Mapping[str, object],
) -> Iterable[RuleFinding]:
    if context.source_path is None:
        return []
    regions = _raw_tex_regions(context)
    if not regions:
        return []
    findings: list[RuleFinding] = []
    graphic_roots: list[str] = []
    for start, end in regions:
        source = context.text[start:end]
        for match in _TEX_GRAPHICSPATH.finditer(source):
            graphic_roots.extend(
                item.group("path").strip()
                for item in _TEX_GRAPHICSPATH_ENTRY.finditer(match.group("paths"))
                if item.group("path").strip()
            )
    for start, end in regions:
        source = context.text[start:end]
        for pattern, kind in ((_TEX_INPUT, "input"), (_TEX_GRAPHICS, "graphics")):
            for match in pattern.finditer(source):
                authored = match.group("path")
                exists = _resource_exists(context, authored, kind, graphic_roots)
                if exists is not False:
                    continue
                path_start = start + match.start("path")
                findings.append(
                    RuleFinding(
                        "tex/missing-resource",
                        "warning",
                        f"No TeX {kind} matching {authored!r} was found relative to "
                        + "this document or the available TeX search paths.",
                        path_start,
                        path_start + len(authored),
                        data={"kind": kind, "path": authored},
                    )
                )
    return findings


def _reference_data(context: RuleContext) -> Mapping[str, object]:
    return _references(context)


def _reference_parts(key: str) -> tuple[str, str, str] | None:
    colon = key.find(":")
    hyphen = key.find("-")
    index = colon if colon > 0 and (hyphen < 0 or colon < hyphen) else hyphen
    if index <= 0 or index >= len(key) - 1:
        return None
    return key[:index], key[index], key[index + 1 :]


def _reference_family(key: str, data: Mapping[str, object]) -> str | None:
    parts = _reference_parts(key)
    if parts is None:
        return None
    prefix = parts[0]
    aliases = _mapping(data.get("family_aliases"))
    if prefix in aliases:
        return str(aliases[prefix])
    families = set(_strings(data.get("reference_families")))
    return prefix if prefix in families else None


def _range(value: object) -> tuple[int, int]:
    mapping = _mapping(value)
    start = mapping.get("from")
    end = mapping.get("to")
    return (
        int(start) if isinstance(start, (int, float)) else 0,
        int(end) if isinstance(end, (int, float)) else 0,
    )


def _div_rule_findings(context: RuleContext, rule: str) -> list[RuleFinding]:
    data = _reference_data(context)
    referenceable = set(_strings(data.get("referenceable_div_classes")))
    proof = set(_strings(data.get("proof_div_classes")))
    theorem_families = set(_strings(data.get("theorem_families")))
    findings: list[RuleFinding] = []
    cursor = 0
    for node in walk_pandoc(context.pandoc_document):
        if node.get("t") != "Div":
            continue
        content = node.get("c")
        if not isinstance(content, list) or len(content) != 2:
            continue
        attr = core.pandoc_attr(content[0])
        if attr is None:
            continue
        identifier, authored_classes, _properties = attr
        classes = [item.casefold() for item in authored_classes]
        refs = [item for item in classes if item in referenceable]
        proofs = [item for item in classes if item in proof]
        needles = tuple(
            item
            for item in (
                f"#{identifier}" if identifier else "",
                *(f".{class_name}" for class_name in authored_classes),
            )
            if item
        )
        start, end = core.locate_after(context.text, needles or (":::",), cursor)
        if end > start:
            cursor = end
        if rule == "reference/multiple-theorem-classes" and len(refs) > 1:
            findings.append(
                RuleFinding(
                    rule,
                    "error",
                    f"This fenced div declares multiple theorem classes: {', '.join(refs)}. "
                    + "These classes assign competing numbering/reference types; remove "
                    + "the classes that do not apply.",
                    start,
                    end,
                )
            )
        elif rule == "reference/theorem-proof-class-conflict" and refs and proofs:
            findings.append(
                RuleFinding(
                    rule,
                    "error",
                    f'This fenced div declares both "{refs[0]}" (numbered) and '
                    + f'"{proofs[0]}" (unnumbered). These classifications conflict; '
                    + "remove one of them.",
                    start,
                    end,
                )
            )
        elif rule == "reference/proof-id-no-target" and identifier and proofs:
            findings.append(
                RuleFinding(
                    rule,
                    "info",
                    f'Proof blocks are unnumbered, so "#{identifier}" does not create '
                    + "a reference target here.",
                    start,
                    end,
                )
            )
        elif (
            rule == "reference/missing-theorem-class"
            and identifier
            and not proofs
            and not refs
        ):
            family = _reference_family(identifier, data)
            if family in theorem_families:
                findings.append(
                    RuleFinding(
                        rule,
                        "error",
                        f'The ID "#{identifier}" uses theorem-family prefix "{family}", '
                        + "but this fenced div has no theorem class. Either change the ID "
                        + "family or add the corresponding theorem class.",
                        start,
                        end,
                        data={
                            "identifier": identifier,
                            "family": family,
                            "classes": tuple(authored_classes),
                        },
                    )
                )
    return findings


def _snapshot_rule_findings(context: RuleContext, rule: str) -> list[RuleFinding]:
    data = _reference_data(context)
    snapshot = _mapping(data.get("snapshot"))
    resolutions = _mapping(data.get("resolutions"))
    class_to_prefix = {
        str(key).casefold(): str(value)
        for key, value in _mapping(data.get("theorem_class_to_prefix")).items()
    }
    referenceable = set(_strings(data.get("referenceable_div_classes")))
    findings: list[RuleFinding] = []

    definitions = snapshot.get("definitions")
    if isinstance(definitions, Sequence) and not isinstance(definitions, str):
        for raw in definitions:
            definition = _mapping(raw)
            key = str(definition.get("key") or "")
            start, end = _range(definition.get("range"))
            resolution = _mapping(resolutions.get(key))
            if (
                rule == "reference/duplicate-workspace-definition"
                and resolution.get("status") == "duplicate"
            ):
                resolution_definitions = resolution.get("definitions")
                sites = (
                    [
                        str(_mapping(item).get("documentPath") or "")
                        for item in resolution_definitions
                    ]
                    if isinstance(resolution_definitions, Sequence)
                    and not isinstance(resolution_definitions, str)
                    else []
                )
                findings.append(
                    RuleFinding(
                        rule,
                        "error",
                        f'Reference "{key}" is defined in more than one place: '
                        + f"{', '.join(sites)}.",
                        start,
                        end,
                        data={"key": key, "definition_paths": tuple(sites)},
                    )
                )
            if (
                rule == "reference/class-family-mismatch"
                and definition.get("sourceKind") == "theorem-div"
            ):
                classes = [
                    item.casefold()
                    for item in _strings(definition.get("classes"))
                    if item.casefold() in referenceable
                ]
                authored = classes[0] if classes else None
                expected = class_to_prefix.get(authored or "")
                actual = str(definition.get("family") or "")
                if authored and expected and actual != expected:
                    parts = _reference_parts(key)
                    separator = ":" if parts is None else parts[1]
                    remainder = key if parts is None else parts[2]
                    findings.append(
                        RuleFinding(
                            rule,
                            "error",
                            f'The block class "{authored}" uses reference family '
                            + f'"{expected}", but its ID is "#{key}". Make the class and '
                            + "ID family agree; for this class the corresponding ID is "
                            + f'"#{expected}{separator}{remainder}".',
                            start,
                            end,
                        )
                    )

    occurrences = snapshot.get("occurrences")
    if (
        rule == "reference/missing-workspace-definition"
        and isinstance(occurrences, Sequence)
        and not isinstance(occurrences, str)
    ):
        for raw in occurrences:
            occurrence = _mapping(raw)
            key = str(occurrence.get("key") or "")
            resolution = _mapping(resolutions.get(key))
            if resolution.get("status") != "missing":
                continue
            family = str(occurrence.get("family") or "")
            parts = _reference_parts(key)
            remainder = (parts[2] if parts else key).casefold()
            candidates: list[str] = []
            cross_family: list[str] = []
            tokens = set(re.split(r"[:_-]+", remainder))
            for candidate_key, raw_resolution in resolutions.items():
                candidate = str(candidate_key)
                candidate_resolution = _mapping(raw_resolution)
                if candidate == key or candidate_resolution.get("status") == "missing":
                    continue
                candidate_family = _reference_family(candidate, data)
                candidate_parts = _reference_parts(candidate)
                candidate_remainder = (
                    candidate_parts[2] if candidate_parts else candidate
                ).casefold()
                if candidate_family == family and any(
                    token in tokens
                    for token in re.split(r"[:_-]+", candidate_remainder)
                ):
                    candidates.append(candidate)
                elif (
                    candidate_family
                    and candidate_family != family
                    and candidate_remainder == remainder
                ):
                    cross_family.append(candidate)
            suffix = ""
            if cross_family:
                suffix = (
                    " A definition with the same stem exists under another reference "
                    + "family: "
                    + ", ".join("@" + item for item in sorted(cross_family))
                    + ". This may be a reference-family mismatch."
                )
            elif candidates:
                suffix = (
                    " Similar defined references: "
                    + ", ".join(sorted(candidates))
                    + "."
                )
            start, end = _range(occurrence.get("range"))
            findings.append(
                RuleFinding(
                    rule,
                    "warning",
                    f'Reference "@{key}" is not defined in the workspace.{suffix}',
                    start,
                    end,
                    data={
                        "key": key,
                        "same_family_candidates": tuple(sorted(candidates)),
                        "cross_family_candidates": tuple(sorted(cross_family)),
                    },
                )
            )
    return findings


def _cite_items(node: Mapping[str, object]) -> list[str]:
    content = node.get("c")
    if not isinstance(content, list):
        return []
    typed_content = cast(list[object], content)
    if len(typed_content) != 2:
        return []
    citations = typed_content[0]
    if not isinstance(citations, list):
        return []
    typed_citations = cast(list[object], citations)
    result: list[str] = []
    for citation in typed_citations:
        item = _mapping(citation)
        citation_id = item.get("citationId")
        if isinstance(citation_id, str):
            result.append(citation_id)
    return result


def _cite_source(node: Mapping[str, object]) -> str:
    content = node.get("c")
    if not isinstance(content, list):
        return ""
    typed_content = cast(list[object], content)
    if len(typed_content) != 2:
        return ""
    return pandoc_plain(cast(PandocJson, typed_content[1]))


def _citation_findings(context: RuleContext, rule: str) -> list[RuleFinding]:
    data = _reference_data(context)
    citation_keys_value = data.get("citation_keys")
    citation_keys = (
        None if citation_keys_value is None else set(_strings(citation_keys_value))
    )
    findings: list[RuleFinding] = []
    cursor = 0
    for node in walk_pandoc(context.pandoc_document):
        if node.get("t") != "Cite":
            continue
        node_mapping = cast(Mapping[str, object], node)
        keys = _cite_items(node_mapping)
        cluster = _cite_source(node_mapping)
        start = context.text.find(cluster, cursor) if cluster else -1
        if start < 0 and cluster:
            start = context.text.find(cluster)
        if start < 0:
            start = cursor
            end = cursor
        else:
            end = start + len(cluster)
            cursor = end
        families = [_reference_family(key, data) for key in keys]
        supported = sum(family is not None for family in families)
        if (
            rule == "citation/mixed-reference-types"
            and supported > 0
            and supported < len(keys)
        ):
            findings.append(
                RuleFinding(
                    rule,
                    "warning",
                    "This citation group mixes bibliography entries and cross-references. "
                    + "Use separate [...] groups so each reference system can interpret "
                    + "its own entries.",
                    start,
                    end,
                )
            )
        if rule == "citation/missing-bibliography-entry" and citation_keys is not None:
            for key, family in zip(keys, families, strict=True):
                if family is not None or key in citation_keys:
                    continue
                key_source = "@{" + key + "}"
                relative = cluster.find(key_source)
                if relative < 0:
                    key_source = "@" + key
                    relative = cluster.find(key_source)
                key_start = start if relative < 0 else start + relative
                findings.append(
                    RuleFinding(
                        rule,
                        "error",
                        f'Bibliography entry "@{key}" was not found.',
                        key_start,
                        key_start + (len(key_source) if relative >= 0 else 0),
                        data={"key": key},
                    )
                )
    return findings


def _tikz_compile_errors(
    context: RuleContext,
    _options: Mapping[str, object],
) -> Iterable[RuleFinding]:
    tikz = _mapping(_compiler(context).get("tikz"))
    value = tikz.get("diagnostics")
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    findings: list[RuleFinding] = []
    for raw in value:
        item = _mapping(raw)
        start, end = _range(item)
        message = item.get("message")
        if isinstance(message, str):
            findings.append(
                RuleFinding(
                    "tikz/compile-error",
                    "error",
                    message,
                    start,
                    end,
                )
            )
    return findings


def _div_check(rule: str) -> RuleCheck:
    def check(
        context: RuleContext,
        options: Mapping[str, object],
        /,
    ) -> Iterable[RuleFinding]:
        del options
        return _div_rule_findings(context, rule)

    return check


def _snapshot_check(rule: str) -> RuleCheck:
    def check(
        context: RuleContext,
        options: Mapping[str, object],
        /,
    ) -> Iterable[RuleFinding]:
        del options
        return _snapshot_rule_findings(context, rule)

    return check


def _citation_check(rule: str) -> RuleCheck:
    def check(
        context: RuleContext,
        options: Mapping[str, object],
        /,
    ) -> Iterable[RuleFinding]:
        del options
        return _citation_findings(context, rule)

    return check


def register_authoring_rules(registry: RuleRegistry) -> None:
    """Register the domain-specific authoring lint rules."""

    registry.register_many(
        (
            LintRule(
                "tex/unknown-command",
                "Math contains a TeX control word with no available definition.",
                check=_unknown_tex_commands,
            ),
            LintRule(
                "math/notation-consistency",
                "Document mixes paired notation variants.",
                RuleLevel.INFO,
                _notation_consistency,
            ),
            LintRule(
                "math/user-macro-candidates",
                "A manual mathematical construction matches one or more known user macros.",
                RuleLevel.INFO,
                _user_macro_candidates,
            ),
            LintRule(
                "document/authorial-residue",
                "Document contains TODO/citation-placeholder residue.",
                RuleLevel.INFO,
                _authorial_residue,
            ),
            LintRule(
                "tex/missing-resource",
                "Static TeX input or graphic cannot be resolved.",
                check=_tex_missing_resource,
            ),
            LintRule(
                "reference/multiple-theorem-classes",
                "Fenced div declares more than one referenceable theorem class.",
                RuleLevel.ERROR,
                _div_check("reference/multiple-theorem-classes"),
            ),
            LintRule(
                "reference/theorem-proof-class-conflict",
                "Fenced div is both a numbered theorem and an unnumbered proof.",
                RuleLevel.ERROR,
                _div_check("reference/theorem-proof-class-conflict"),
            ),
            LintRule(
                "reference/proof-id-no-target",
                "Proof-like fenced div carries an ID which is not a reference target.",
                RuleLevel.INFO,
                _div_check("reference/proof-id-no-target"),
            ),
            LintRule(
                "reference/missing-theorem-class",
                "Theorem-family ID appears on a div without a theorem class.",
                RuleLevel.ERROR,
                _div_check("reference/missing-theorem-class"),
            ),
            LintRule(
                "reference/duplicate-workspace-definition",
                "Reference key has multiple workspace definitions.",
                RuleLevel.ERROR,
                _snapshot_check("reference/duplicate-workspace-definition"),
            ),
            LintRule(
                "reference/class-family-mismatch",
                "Theorem div class and authored reference family disagree.",
                RuleLevel.ERROR,
                _snapshot_check("reference/class-family-mismatch"),
            ),
            LintRule(
                "reference/missing-workspace-definition",
                "Reference occurrence has no workspace definition.",
                check=_snapshot_check("reference/missing-workspace-definition"),
            ),
            LintRule(
                "citation/mixed-reference-types",
                "Citation cluster mixes bibliography citations and cross-references.",
                check=_citation_check("citation/mixed-reference-types"),
            ),
            LintRule(
                "citation/missing-bibliography-entry",
                "Bibliography citation key is absent from the active bibliography.",
                RuleLevel.ERROR,
                _citation_check("citation/missing-bibliography-entry"),
            ),
            LintRule(
                "tikz/compile-error",
                "TikZ compiler reported an authored-source error.",
                RuleLevel.ERROR,
                _tikz_compile_errors,
            ),
        )
    )


__all__ = ("register_authoring_rules",)
