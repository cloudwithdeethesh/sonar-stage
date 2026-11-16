# Planted Sonar findings

Every file under `samples/py/` holds intentional Sonar bait: code written to
be flagged by SonarQube, kept out of production paths, and excluded from
coverage computation via `sonar.coverage.exclusions=samples/**` in
`sonar-project.properties`.

Each planted issue carries a `# PLANTED: <idea>` marker on its triggering
line. That marker has two jobs:

- It documents **why** the smell is there, for reviewers.
- It exempts the line from `/finish-milestone`'s entropy-based secret scan,
  so credential-shaped strings and long identifiers don't abort commits.

`src/` also carries three planted markers on otherwise-shipped code, so
Sonar produces findings on the "real" project too. Those three are counted
toward coverage (either tested or on exercised paths) and do not push the
coverage number outside the 70–85 % target band.

## Inventory

Regenerate with:

```
grep -En '# PLANTED' samples/py/*.py src/*.py | grep -v '<idea>'
```

| File | Line | Planted idea |
|------|------|--------------|
| `samples/py/dirty_duplicated_a.py` | 5 | duplicated 20-line block (pair with dirty_duplicated_b.py) |
| `samples/py/dirty_duplicated_b.py` | 4 | duplicated 20-line block (pair with dirty_duplicated_a.py) |
| `samples/py/dirty_security.py` | 14 | weak hardcoded password |
| `samples/py/dirty_security.py` | 15 | hardcoded credential |
| `samples/py/dirty_security.py` | 19 | eval on user input |
| `samples/py/dirty_security.py` | 23 | subprocess with shell=True |
| `samples/py/dirty_security.py` | 27 | os.system with concatenated user input |
| `samples/py/dirty_security.py` | 31 | MD5 used for password hashing |
| `samples/py/dirty_security.py` | 35 | pickle.loads on untrusted data |
| `samples/py/dirty_security.py` | 40 | SQL via string concatenation |
| `samples/py/dirty_security.py` | 45 | hardcoded /tmp path |
| `samples/py/dirty_security.py` | 48 | world-writable chmod (0o777) |
| `samples/py/dirty_smells.py` | 3 | unused import (json) |
| `samples/py/dirty_smells.py` | 5 | unused import (sys) |
| `samples/py/dirty_smells.py` | 9 | unused local variable (dead store) |
| `samples/py/dirty_smells.py` | 15 | division by zero |
| `samples/py/dirty_smells.py` | 20 | off-by-one in range |
| `samples/py/dirty_smells.py` | 25 | mutable default argument |
| `samples/py/dirty_smells.py` | 31 | file opened without closing |
| `samples/py/dirty_smells.py` | 39 | bare except that swallows errors (pass follows) |
| `src/formatters.py` | 19 | duplicates calculate_tax from src.receipts |
| `src/receipts.py` | 19 | duplicated literal "0.01" across this module |
| `src/validators.py` | 14 | magic number 254 (should be a named constant) |

Line numbers drift when the files change — the grep above always reflects
reality. The baseline run in milestone 3 will compare this inventory
against the SonarQube findings and flag any plant that isn't picked up.
