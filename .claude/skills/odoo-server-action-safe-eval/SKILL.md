---
name: odoo-server-action-safe-eval
description: Use when writing, editing, or debugging an Odoo Server Action (ir.actions.server, python_code / safe_eval), including errors like "name 'getattr' is not defined", "name 'fields' is not defined", or forbidden-opcode / STORE_ATTR validation failures.
---

# Odoo Server Action safe_eval

## Overview

Server Action `python_code` runs inside Odoo's `safe_eval` sandbox: a whitelist of
builtins plus a fixed eval context, with several bytecode opcodes blacklisted. The
validator inspects the **whole bytecode BEFORE running**, so a forbidden statement
fails even when it sits inside `if not DRY_RUN:` or a branch that never executes.
Lists below are verified against the Odoo 17 source (see "Verify" section).

## When to use

- Writing or editing any `ir.actions.server` of type *code*.
- Debugging `name 'X' is not defined` or an opcode/validation error from a Server Action.

## Forbidden → canonical replacement

| Forbidden | Why it fails | Use instead |
|---|---|---|
| `getattr / setattr / hasattr / delattr` | not in builtins → `name 'getattr' is not defined` | `('f' in rec._fields) and rec.f` ; write via `.write()` |
| `obj.attr = x` | opcode `STORE_ATTR` blacklisted | `obj.write({'attr': x})` |
| `del obj.attr` | opcode `DELETE_ATTR` | `obj.write({'attr': False})` |
| `import re / base64 / ...` | opcodes `IMPORT_NAME/FROM/STAR` | string ops; for base64 use the injected `b64encode`/`b64decode` |
| `global x` | opcode `STORE_GLOBAL` | mutate a dict/list defined in scope |
| `fields.Date.today()` | `fields` is NOT injected | `datetime.date.today()` (has `.isoformat()`, `.replace()`, `timedelta`) |
| `type(x)` / `eval` / `exec` / `open` / `print` / `vars` / `dir` | not in builtins | `isinstance(x, T)` ; `log(msg)` instead of `print` |
| `x.__class__` / `x.__globals__` / `x.__code__` | `_UNSAFE_ATTRIBUTES` blocked | no introspection of internals |

**Gotcha:** `A and getattr(x, 'f', '')` only raises when `A` is truthy (short-circuit),
so it fails *intermittently* and is easy to miss in a loop.

## Allowed builtins (Odoo 17 `_BUILTINS`)

`True False None bool int float str bytes dict list tuple set enumerate map filter zip
sorted reduce range abs min max sum round len repr ord chr divmod isinstance any all
Exception`

## Eval context injected (Server Action — 17 names)

`env, model, record, records, log, _logger, UserError, Command, uid, user, time,
datetime, dateutil, timezone, float_compare, b64encode, b64decode`

`b64encode`/`b64decode` ARE available even though `import base64` is not. `def` and
`lambda`, list/dict comprehensions, and `env.cr.execute(sql)` (incl. `TRUNCATE`) are allowed.

## Return value

Assign a dict to `action` (the run is `nocopy=True`). Notification:
`{'type':'ir.actions.client','tag':'display_notification','params':{'title','message','type','sticky'}}`.
File download: create `ir.attachment` (`raw=txt.encode('utf-8-sig')`, `mimetype='text/csv'`)
then `{'type':'ir.actions.act_url','url':'/web/content/%s?download=true' % att.id}`.

## Verify a doubtful name/statement (don't guess)

- Builtins + blacklisted opcodes: `odoo/tools/safe_eval.py` → `_BUILTINS`, `_BLACKLIST`,
  `_UNSAFE_ATTRIBUTES`.
- Injected context: `odoo/addons/base/models/ir_actions.py` →
  `IrActionsServer._get_eval_context`.
- Pinned online: `raw.githubusercontent.com/odoo/odoo/<version>/odoo/tools/safe_eval.py`.
- Empirical: run a tiny Server Action with just the doubtful call and read the error.

## Common mistakes

- Trusting a branch guard to dodge the validator — it checks all bytecode first.
- Reaching for `import base64` when `b64decode` is already in context.
- Studio `x_*` models: `x_name` is NOT NULL (required) → set it in every `create()`.
- Heavy product / move.line sweeps belong server-side here, NOT via XML-RPC (XML-RPC from
  a PC hammers the POS cache).
