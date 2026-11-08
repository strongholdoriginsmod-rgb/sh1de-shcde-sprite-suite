"""Read argparse declarations without importing or executing a tool."""
from __future__ import annotations
import ast
from pathlib import Path
import shlex
import argparse
import copy


def walk_source(node):
    yield node
    for child in ast.iter_child_nodes(node):yield from walk_source(child)


class ExpandParserLoops(ast.NodeTransformer):
    """Expand literal parser declarations without executing the script."""
    def visit_For(self,node):
        if not isinstance(node.iter,(ast.Tuple,ast.List)) or not any(
            isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
            and n.func.attr in {'add_parser','add_argument'} for n in ast.walk(node)):
            return self.generic_visit(node)
        result=[]
        for item in node.iter.elts:
            pairs=list(zip(node.target.elts,item.elts)) if isinstance(node.target,ast.Tuple) and isinstance(item,ast.Tuple) else [(node.target,item)]
            bindings={target.id:value for target,value in pairs if isinstance(target,ast.Name)}
            class Substitute(ast.NodeTransformer):
                def visit_Name(self,name):
                    return copy.deepcopy(bindings[name.id]) if isinstance(name.ctx,ast.Load) and name.id in bindings else name
            for statement in node.body:
                expanded=self.visit(Substitute().visit(copy.deepcopy(statement)))
                result.extend(expanded if isinstance(expanded,list) else [expanded])
        return result

    def visit_If(self,node):
        test=node.test;known=False;decision=False
        if isinstance(test,ast.Compare) and len(test.ops)==1:
            missing=object();left=literal(test.left,missing);right=literal(test.comparators[0],missing)
            if left is not missing and right is not missing:
                op=test.ops[0]
                if isinstance(op,ast.Eq):known=True;decision=left==right
                elif isinstance(op,ast.NotEq):known=True;decision=left!=right
                elif isinstance(op,ast.In):known=True;decision=left in right
                elif isinstance(op,ast.NotIn):known=True;decision=left not in right
        if known:
            result=[]
            for statement in node.body if decision else node.orelse:
                expanded=self.visit(statement)
                result.extend(expanded if isinstance(expanded,list) else [expanded])
            return result
        return self.generic_visit(node)


def describe_parser(parser):
    fields=[]; commands=[]
    def visit(current, command):
        commands.append(command)
        for action in current._actions:
            if isinstance(action, argparse._HelpAction): continue
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items(): visit(child, (*command,name))
                continue
            kind = 'store_true' if isinstance(action,argparse._StoreTrueAction) else 'store_false' if isinstance(action,argparse._StoreFalseAction) else 'store'
            fields.append({'names':action.option_strings or [action.dest], 'command':command,
                           'action':kind,'required':action.required,'nargs':action.nargs,
                           'choices':list(action.choices) if action.choices is not None else None,
                           'help':action.help})
    visit(parser,())
    return {'description':parser.description or parser.prog,'commands':commands,'fields':fields}


def literal(node, default=None):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return default


def describe(path: Path):
    tree = ExpandParserLoops().visit(ast.parse(path.read_text(encoding='utf-8-sig')))
    bindings = {}
    fields = []
    commands = {()}
    cli_description = None
    for node in walk_source(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not isinstance(call.func, ast.Attribute):
                continue
            owner = call.func.value.id if isinstance(call.func.value, ast.Name) else ''
            if call.func.attr == 'ArgumentParser':
                bindings[target.id] = ()
                for kw in call.keywords:
                    if kw.arg == 'description' and cli_description is None:
                        candidate = literal(kw.value)
                        if isinstance(candidate, str) and candidate.strip():
                            cli_description = candidate
            elif call.func.attr in {'add_subparsers','add_mutually_exclusive_group','add_argument_group'}:
                bindings[target.id] = bindings.get(owner,())
            elif call.func.attr == 'add_parser' and call.args:
                name = literal(call.args[0])
                if isinstance(name,str):
                    bindings[target.id] = (*bindings.get(owner,()),name)
                    commands.add(bindings[target.id])
        if not isinstance(node, ast.Call) or not isinstance(node.func,ast.Attribute) or node.func.attr != 'add_argument':
            continue
        if not isinstance(node.func.value,ast.Name):
            continue
        names = [literal(a) for a in node.args]
        if not names or not all(isinstance(n,str) for n in names):
            continue
        kw = {k.arg:literal(k.value) for k in node.keywords if k.arg}
        field = {'names':names,'command':bindings.get(node.func.value.id,()),**kw}
        if not any(f['names']==names and f['command']==field['command'] for f in fields):
            fields.append(field)
    return {'description':ast.get_docstring(tree) or cli_description or path.name,
            'commands':sorted(commands),'fields':fields}


def format_static_help(metadata: dict, command: tuple[str, ...] = (),
                       *, limit: int = 6500) -> str:
    """Describe an already-parsed CLI without importing or executing the tool.

    This is an approximate static source view, NOT argparse's live --help.
    Runtime-generated options may be missing. It is safe even for a script
    with malicious top-level statements, because those are never run.
    """
    if limit < 250:
        raise ValueError("Help display limit is too short")
    title = str(metadata.get("description") or "Undokumentiertes Werkzeug")
    commands = tuple(tuple(c) for c in metadata.get("commands", ()))
    lines = [
        "Statische Werkzeughilfe – kein Skript gestartet",
        "",
        title,
        "",
        "Quelle: vorhandene Parser-/AST-Deklarationen, ohne Import/Ausführung.",
        "Dynamisch erzeugte CLI-Optionen können fehlen.",
    ]
    if commands and commands != ((),):
        lines.extend(("", "Erkannte Befehle:"))
        lines.extend("  " + (" ".join(c) if c else "(Standard)")
                     for c in commands)
    if command:
        lines.extend(("", "Gewählte Aktion: " + " ".join(command)))
    filtered = [f for f in metadata.get("fields", ())
                if not command or tuple(f.get("command", ())) == ()
                or tuple(f.get("command", ())) == tuple(command)]
    if filtered:
        lines.extend(("", "Argumente / Optionen dieser Aktion:"))
        for item in filtered:
            names = " / ".join(map(str, item.get("names", ())))
            origin = tuple(item.get("command", ()))
            scope = ("[" + " ".join(origin) + "] ") if origin and not command else ""
            required = " [Pflichtfeld]" if item.get("required") else ""
            choices = item.get("choices")
            extra = (" {" + ", ".join(map(str, choices)) + "}") if choices else ""
            help_text = str(item.get("help") or "").strip().replace("\n", " ")
            lines.append("  " + scope + names + required + extra)
            if help_text:
                lines.append("    " + help_text)
    else:
        lines.extend(("", "Keine statisch auswertbaren Argumente gefunden.",
                      "Bitte fachliche Projektdokumentation beachten."))
    output = "\n".join(lines)
    if len(output) > limit:
        output = output[:limit - 85].rstrip() + (
            "\n\n[Anzeige gekürzt; weitere Details im Quelltext. Kein Tool ausgeführt.]")
    return output


def tokens_for(command, fields, values, extra=''):
    groups = {tuple(command[:depth]): [] for depth in range(len(command)+1)}
    for field,value in zip(fields,values):
        result = groups.setdefault(tuple(field.get('command', ())), [])
        names=field['names']
        name=next((n for n in names if n.startswith('--')),names[0])
        if field.get('action') in {'store_true','store_false'}:
            if value:
                result.append(name)
            continue
        value=str(value).strip()
        if not value:
            if field.get('required') or (not name.startswith('-') and field.get('nargs') not in {'?','*'}):
                raise ValueError('Pflichtfeld fehlt: '+name)
            continue
        if name.startswith('-'):
            result.append(name)
        if field.get('nargs') in {'+','*'} or isinstance(field.get('nargs'),int):
            result.extend(split_arguments(value))
        else:
            result.append(value)
    result = list(groups[()])
    for depth, name in enumerate(command, 1):
        result.append(name)
        result.extend(groups[tuple(command[:depth])])
    result.extend(split_arguments(extra))
    return result


def split_arguments(text):
    # Keep backslashes in Windows paths; remove only balanced quote wrappers.
    return [token[1:-1] if len(token)>=2 and token[0]==token[-1] and token[0] in {'"',"'"} else token
            for token in shlex.split(text,posix=False)]
