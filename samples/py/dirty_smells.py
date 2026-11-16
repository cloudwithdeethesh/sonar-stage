"""Intentional Sonar bait — code smells only, no credentials here."""

import json  # PLANTED: unused import (json)
import os
import sys  # PLANTED: unused import (sys)


def unused_var_demo():
    computed = 42  # PLANTED: unused local variable (dead store)
    return "done"


def div_by_zero():
    denominator = 0
    return 10 / denominator  # PLANTED: division by zero


def off_by_one(items):
    total = 0
    for i in range(len(items) + 1):  # PLANTED: off-by-one in range
        total += items[i]
    return total


def mutable_default(acc=[]):  # PLANTED: mutable default argument
    acc.append(1)
    return acc


def leaked_file():
    f = open(os.devnull, "w")  # PLANTED: file opened without closing
    f.write("x")
    return "done"


def bare_except_swallow():
    try:
        return 1 / 0
    except:  # PLANTED: bare except that swallows errors (pass follows)
        pass
    return None
